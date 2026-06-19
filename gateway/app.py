"""
FastAPI gateway — HTTP + WebSocket server.

The gateway is the single entry point for the browser:
  GET  /api/health       — liveness probe
  GET  /api/status       — system status snapshot
  WS   /ws               — real-time event stream (bus → browser)

WebSocket protocol:
  Server → client: EventEnvelope serialised as JSON (one object per message).
  Client → server: ignored for now; reserved for future commands/filters.

Dev usage:
  uvicorn gateway.app:app --reload --port 8000

The Vite dev server proxies /api and /ws to this port (vite.config.ts),
so the frontend never needs CORS headers in development.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from calibration import CalibrationEngine, CalibrationSettings, GateTracker, OutcomeResolver
from core.bus import InProcessBus
from core.bus.store import SqliteEventStore
from core.db import migrate, open_db
from core.logging import configure_logging
from core.mode import ModeController
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from discovery import DiscoverySettings
from ingestion.alerts import PriceAlertGenerator
from ingestion.congress import CongressFeed
from ingestion.equity import EquityFeed
from ingestion.govexposure import GovExposureFeed
from ingestion.insider import InsiderFeed
from ingestion.supplychain import SupplyChainFeed
from ingestion.kraken import KrakenFeed
from ingestion.news import NewsFeed
from ingestion.pruner import TickPruner
from ingestion.router import FeedRouter
from portfolio import PaperExecutor, Portfolio
from reasoning.decision import DecisionGenerator
from reasoning.llm import CachingProvider, JsonFileLLMCache, LLMSettings, create_provider
from reasoning.thesis import ThesisGenerator, ThesisInvalidator
from risk import RiskEngine
from watchlist import SqliteWatchlistStore, WatchlistManager

from .broadcaster import Broadcaster
from .routes import (
    analytics_router,
    calibration_router,
    chart_router,
    decisions_router,
    discovery_router,
    events_router,
    halt_router,
    mode_router,
    portfolio_router,
    watchlist_router,
)
from .settings import GatewaySettings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Default lifespan (production)
# ---------------------------------------------------------------------------


async def _reconcile_orphan_positions(
    store: SqliteEventStore,
    portfolio: Portfolio,
    executor: PaperExecutor,
    decision_store: dict[str, Any],
) -> None:
    """Close open positions whose governing thesis has expired or been invalidated.

    A position should be flat once its thesis dies, but close-on-invalidation is a
    one-shot event that's lost if it can't fill or fires while we're down. This
    walks position → decision → thesis from the audit log and hands any dead-thesis
    instruments to the executor (which closes now, or defers to the first tick)."""
    created = await store.recent([EventType.THESIS_CREATED.value], limit=5000)
    invalidated = await store.recent([EventType.THESIS_INVALIDATED.value], limit=5000)
    invalidated_tids = {
        str(e.payload.get("thesis_id")) for e in invalidated if e.payload.get("thesis_id")
    }
    horizon_by_tid: dict[str, tuple[datetime, int]] = {}
    for e in created:
        tid = str(e.payload.get("id", ""))
        if tid:
            horizon_by_tid[tid] = (e.event_time, int(e.payload.get("time_horizon_hours", 8)))

    now = datetime.now(UTC)
    orphans: list[str] = []
    for instrument, pos in portfolio.positions.items():
        dec = decision_store.get(pos.decision_id)
        raw_tid = dec.get("originating_thesis_id") if dec else None
        pos_tid = str(raw_tid) if raw_tid else None
        if pos_tid is None or pos_tid in invalidated_tids:
            # No traceable thesis, or one explicitly invalidated → dead.
            dead = True
        elif pos_tid in horizon_by_tid:
            created_at, horizon = horizon_by_tid[pos_tid]
            dead = created_at + timedelta(hours=horizon) <= now
        else:
            dead = True  # thesis not found in history → long expired
        if dead:
            orphans.append(instrument)

    if orphans:
        logger.warning("gateway.orphan_positions_reconciled", instruments=orphans)
        await executor.reconcile_orphans(orphans, now)


@asynccontextmanager
async def default_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    logger.info("gateway.starting")

    conn = await open_db()
    await migrate(conn)

    store = SqliteEventStore(conn)
    bus = InProcessBus(store)

    broadcaster = Broadcaster(bus)
    await broadcaster.start()

    # Phase 5: watchlist — must start before feeds so the active instrument
    # set is populated before FeedRouter subscribes to anything.
    watchlist_store = SqliteWatchlistStore(conn)
    watchlist_manager = WatchlistManager(bus, watchlist_store)
    await watchlist_manager.start()

    alert_generator = PriceAlertGenerator(bus, watchlist=watchlist_manager)
    await alert_generator.start()

    # Record every LLM response keyed by prompt hash — recorded responses
    # power deterministic, free backtest replays (python -m backtest).
    llm_settings = LLMSettings()
    provider = CachingProvider(
        JsonFileLLMCache(llm_settings.cache_path),
        inner=create_provider(llm_settings),
    )
    thesis_generator = ThesisGenerator(bus, provider, watchlist=watchlist_manager)
    await thesis_generator.start()

    # store passed so the invalidator can rehydrate active theses after a
    # restart (otherwise pre-restart theses never expire).
    thesis_invalidator = ThesisInvalidator(bus, store)
    await thesis_invalidator.start()

    # Decision store: tracks all decisions by ID for the REST API
    decision_store: dict[str, Any] = {}

    async def _track_decision(envelope: EventEnvelope) -> None:
        p = envelope.payload
        if envelope.event_type == EventType.DECISION_EXPIRED.value:
            # Expired carries only {decision_id, reason} — update the existing
            # record's status instead of overwriting the full decision with the
            # stub, so a parked decision that ages out stops reading 'approved'.
            did = p.get("decision_id")
            if did and did in decision_store:
                decision_store[did] = {
                    **decision_store[did], "status": "expired", "_event_type": envelope.event_type
                }
            return
        did = p.get("id")
        if did:
            decision_store[did] = {**p, "_event_type": envelope.event_type}

    decision_event_types = [
        EventType.DECISION_PROPOSED.value,
        EventType.DECISION_APPROVED.value,
        EventType.DECISION_REJECTED.value,
        EventType.DECISION_EXPIRED.value,
    ]
    for event_type in decision_event_types:
        await bus.subscribe(event_type, _track_decision)
    # Rebuild the decision store from recent history so the REST API isn't empty
    # after a restart. recent() is chronological, so the latest event per id
    # wins — the same reduction the live tracker applies.
    for envelope in await store.recent(decision_event_types, limit=2000):
        await _track_decision(envelope)

    # Phase 3: risk + paper trading pipeline.
    # One ModeController is the single source of truth for the autonomy mode;
    # every component reads it rather than caching its own copy, so a dropped or
    # reordered mode-change event can't leave subsystems trading in different
    # modes. Restart fail-safe: always starts in OBSERVE (core.mode, ADR-004).
    mode_controller = ModeController(bus, initial=AutonomyMode.OBSERVE)
    portfolio = Portfolio(bus)
    # Rehydrate the paper book from the full order.filled history before
    # subscribing — otherwise a restart resets cash to initial_cash and drops
    # open positions, corrupting the autonomy gate's P&L evidence window.
    filled_events = await store.range([EventType.ORDER_FILLED.value])
    await portfolio.rehydrate(filled_events)
    # Seed marks from the last persisted tick per instrument so unrealized P&L is
    # correct on restart even when the market is closed and no live tick will come.
    portfolio.seed_prices(await store.latest_per_key([EventType.MARKET_TICK.value], "instrument"))
    await portfolio.start()

    risk_engine = RiskEngine(bus, portfolio, modes=mode_controller)
    await risk_engine.start()

    # Inject the risk engine's pre-trade evaluation so a parked ASSISTED
    # decision is re-validated (and its size/stop recomputed) at execute time.
    executor = PaperExecutor(
        bus, portfolio, modes=mode_controller, validator=risk_engine.evaluate
    )
    # Re-park ASSISTED approvals that never reached a terminal state, so a hard
    # crash doesn't silently lose the operator's decision queue (graceful
    # shutdown already drains it via stop()). Terminal = filled (open), rejected,
    # or already expired. Built from the audit log before subscribing.
    executed_ids = {
        f.payload.get("decision_id", "")
        for f in filled_events
        if f.payload.get("action") == "open"
    }
    rejected_ids = {
        str(e.payload.get("id", ""))
        for e in await store.recent([EventType.DECISION_REJECTED.value], limit=2000)
    }
    expired_ids = {
        str(e.payload.get("decision_id", ""))
        for e in await store.recent([EventType.DECISION_EXPIRED.value], limit=2000)
    }
    await executor.rehydrate_pending(
        await store.recent([EventType.DECISION_APPROVED.value], limit=2000),
        executed_ids | rejected_ids | expired_ids,
        datetime.now(UTC),
    )
    await executor.start()

    # Restart reconciliation: a position must not outlive its thesis. The
    # close-on-invalidation event is best-effort (lost if it fired with no
    # price, before the executor subscribed, or while the process was down), so
    # re-enforce the invariant here from the audit log. Thesis liveness is read
    # straight from thesis.created/.invalidated history — independent of the
    # invalidator's rehydrate window — so a long-horizon thesis isn't misjudged.
    if portfolio.positions:
        await _reconcile_orphan_positions(store, portfolio, executor, decision_store)

    decision_generator = DecisionGenerator(bus, provider, watchlist=watchlist_manager)
    await decision_generator.start()

    # Phase 4: outcome resolution + calibration.
    # Rehydrate from the audit log before live feeds start: resolved history
    # feeds the calibration engine; still-unresolved proposals are re-tracked
    # and caught up against recent tick history so restarts don't orphan them.
    calibration_settings = CalibrationSettings()
    resolver = OutcomeResolver(bus, modes=mode_controller, settings=calibration_settings)
    calibration_engine = CalibrationEngine(bus, settings=calibration_settings)
    gate_tracker = GateTracker(
        bus, calibration_engine, settings=calibration_settings, trade_book=portfolio
    )

    resolved_events = await store.recent([EventType.DECISION_RESOLVED.value], limit=2000)
    calibration_engine.seed(resolved_events)
    # Restore the lifetime limit-breach count so the "0 breaches" gate criterion
    # survives restarts instead of silently resetting to 0 (range = all-time).
    gate_tracker.seed(await store.range([EventType.RISK_LIMIT_BREACHED.value]))
    resolved_ids = {str(e.payload.get("decision_id", "")) for e in resolved_events}
    # The historical mode isn't recorded on the proposal, so derive it from the
    # risk verdict: an observe_mode rejection marks a shadow decision; anything
    # else was proposed under paper/assisted (both fill on the paper executor).
    shadow_ids = {
        str(e.payload.get("id", ""))
        for e in await store.recent([EventType.DECISION_REJECTED.value], limit=2000)
        if any(
            r.startswith("observe_mode")
            for r in (e.payload.get("risk") or {}).get("rejection_reasons", [])
        )
    }
    unresolved = [
        (e, AutonomyMode.OBSERVE if did in shadow_ids else AutonomyMode.PAPER)
        for e in await store.recent([EventType.DECISION_PROPOSED.value], limit=2000)
        if (did := str(e.payload.get("id", ""))) not in resolved_ids
    ]
    resolver.seed(unresolved)
    await resolver.replay(
        await store.recent(
            [EventType.MARKET_TICK.value, EventType.THESIS_INVALIDATED.value], limit=5000
        )
    )
    await resolver.start()
    await calibration_engine.start()
    await gate_tracker.start()

    # Phase 5: feeds — KrakenFeed starts with empty subscription;
    # FeedRouter.start() subscribes the watchlist instruments.
    kraken_feed = KrakenFeed(bus, settings=None)
    # Clear static products so FeedRouter owns all subscriptions.
    kraken_feed._active_instruments.clear()

    equity_feed = EquityFeed(bus)

    feed_router = FeedRouter(bus, watchlist_manager, kraken_feed, equity_feed)
    await feed_router.start()

    feed_task = asyncio.create_task(kraken_feed.run(), name="kraken_feed")
    equity_task = asyncio.create_task(equity_feed.run(), name="equity_feed")

    tick_pruner = TickPruner(store)
    await tick_pruner.start()

    # Seed cross-restart dedup from the audit log so restarting doesn't
    # re-publish headlines already emitted as signals.
    seen_links = {
        sid
        for e in await store.recent(
            [EventType.SIGNAL_CREATED.value], limit=500, payload_type=["news"]
        )
        if e.source == "rss_news_feed"
        and (sid := e.payload.get("provenance", {}).get("source_id"))
    }
    news_feed = NewsFeed(bus, initial_seen=seen_links, watchlist=watchlist_manager)
    news_task = asyncio.create_task(news_feed.run(), name="news_feed")

    # Phase 6A: alternative-data ingestion. InsiderFeed (SEC Form 4) emits for all
    # material filings market-wide; the ThesisGenerator watchlist gate keeps it
    # enrich-only (ADR-010). No watchlist filter here — unwatched-ticker filings
    # are still persisted for audit / Phase 6B discovery.
    seen_accessions = {
        sid
        for e in await store.recent(
            [EventType.SIGNAL_CREATED.value], limit=500, payload_type=["insider_tx"]
        )
        if e.source == "sec_edgar_form4"
        and (sid := e.payload.get("provenance", {}).get("source_id"))
    }
    insider_feed = InsiderFeed(bus, initial_seen=seen_accessions)
    insider_task = asyncio.create_task(insider_feed.run(), name="insider_feed")

    # CongressFeed (Quiver) no-ops without QUIVER_API_TOKEN; same enrich-only path.
    seen_congress = {
        sid
        for e in await store.recent(
            [EventType.SIGNAL_CREATED.value], limit=500, payload_type=["congressional_tx"]
        )
        if e.source == "quiver_congress"
        and (sid := e.payload.get("provenance", {}).get("source_id"))
    }
    congress_feed = CongressFeed(bus, initial_seen=seen_congress)
    congress_task = asyncio.create_task(congress_feed.run(), name="congress_feed")

    # GovExposureFeed (Senate LDA + USASpending) — per watched-equity, free, no key
    # required. Inert until the watchlist holds equities. Enrich-only by construction.
    seen_gov = {
        sid
        for e in await store.recent(
            [EventType.SIGNAL_CREATED.value],
            limit=1000,
            payload_type=["lobbying", "gov_contract"],
        )
        if e.source in ("senate_lda", "usaspending")
        and (sid := e.payload.get("provenance", {}).get("source_id"))
    }
    govexposure_feed = GovExposureFeed(bus, watchlist_manager, initial_seen=seen_gov)
    govexposure_task = asyncio.create_task(govexposure_feed.run(), name="govexposure_feed")

    # SupplyChainFeed (10-K customer concentration) — per watched-equity, free, no key.
    seen_supplychain = {
        sid
        for e in await store.recent(
            [EventType.SIGNAL_CREATED.value], limit=500, payload_type=["supply_chain"]
        )
        if e.source == "sec_10k"
        and (sid := e.payload.get("provenance", {}).get("source_id"))
    }
    supplychain_feed = SupplyChainFeed(bus, watchlist_manager, initial_seen=seen_supplychain)
    supplychain_task = asyncio.create_task(supplychain_feed.run(), name="supplychain_feed")

    # Store on app.state so route handlers can access them.
    app.state.bus = bus
    app.state.broadcaster = broadcaster
    app.state.conn = conn
    app.state.event_store = store
    app.state.mode_controller = mode_controller
    app.state.portfolio = portfolio
    app.state.executor = executor
    app.state.decision_store = decision_store
    app.state.calibration_engine = calibration_engine
    app.state.gate_tracker = gate_tracker
    app.state.watchlist_manager = watchlist_manager
    app.state.discovery_settings = DiscoverySettings()
    app.state.llm_provider = provider

    logger.info("gateway.ready")
    yield  # ← app serves requests here

    logger.info("gateway.shutting_down")

    for task in (
        feed_task, equity_task, news_task, insider_task, congress_task, govexposure_task,
        supplychain_task,
    ):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await tick_pruner.stop()
    await feed_router.stop()
    await gate_tracker.stop()
    await calibration_engine.stop()
    await resolver.stop()
    await decision_generator.stop()
    await executor.stop()
    await risk_engine.stop()
    await portfolio.stop()
    await thesis_invalidator.stop()
    await thesis_generator.stop()
    await alert_generator.stop()
    await watchlist_manager.stop()
    await broadcaster.stop()
    await bus.close()
    await conn.close()

    logger.info("gateway.stopped")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(lifespan: Any = default_lifespan) -> FastAPI:
    """
    Returns a configured FastAPI application.

    Pass a custom lifespan in tests to avoid starting real feeds and DB.

        app = create_app(lifespan=test_lifespan)
    """
    settings = GatewaySettings()

    app = FastAPI(
        title="AFTERHOURS",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_routes(app)
    app.include_router(mode_router)
    app.include_router(decisions_router)
    app.include_router(portfolio_router)
    app.include_router(halt_router)
    app.include_router(events_router)
    app.include_router(calibration_router)
    app.include_router(watchlist_router)
    app.include_router(analytics_router)
    app.include_router(discovery_router)
    app.include_router(chart_router)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        broadcaster: Broadcaster = app.state.broadcaster
        return {
            "status": "ok",
            "timestamp": datetime.now(UTC).isoformat(),
            "connected_clients": broadcaster.client_count,
            # Non-zero and growing ⇒ a client can't keep up with the event rate;
            # it sheds its own backlog rather than stalling the bus.
            "dropped_messages": broadcaster.total_dropped,
        }

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        broadcaster: Broadcaster = websocket.app.state.broadcaster
        await broadcaster.connect(websocket)
        try:
            while True:
                # Read loop: keeps the connection alive and detects disconnect.
                # Reserved for future client→server messages (filters, commands).
                await websocket.receive_text()
        except WebSocketDisconnect:
            broadcaster.disconnect(websocket)
        except Exception:
            # Catch-all: any unexpected error also cleans up the client.
            broadcaster.disconnect(websocket)


# ---------------------------------------------------------------------------
# Module-level app instance — loaded by uvicorn
# ---------------------------------------------------------------------------

app = create_app()
