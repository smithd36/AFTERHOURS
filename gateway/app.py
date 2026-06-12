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
from datetime import UTC, datetime
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
from ingestion.alerts import PriceAlertGenerator
from ingestion.equity import EquityFeed
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
    calibration_router,
    decisions_router,
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

    thesis_invalidator = ThesisInvalidator(bus)
    await thesis_invalidator.start()

    # Decision store: tracks all decisions by ID for the REST API
    decision_store: dict[str, Any] = {}

    async def _track_decision(envelope: EventEnvelope) -> None:
        p = envelope.payload
        did = p.get("id")
        if did:
            decision_store[did] = {**p, "_event_type": envelope.event_type}

    decision_event_types = [
        EventType.DECISION_PROPOSED.value,
        EventType.DECISION_APPROVED.value,
        EventType.DECISION_REJECTED.value,
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
    await portfolio.rehydrate(await store.range([EventType.ORDER_FILLED.value]))
    await portfolio.start()

    risk_engine = RiskEngine(bus, portfolio, modes=mode_controller)
    await risk_engine.start()

    # Inject the risk engine's pre-trade evaluation so a parked ASSISTED
    # decision is re-validated (and its size/stop recomputed) at execute time.
    executor = PaperExecutor(
        bus, portfolio, modes=mode_controller, validator=risk_engine.evaluate
    )
    await executor.start()

    decision_generator = DecisionGenerator(bus, provider, watchlist=watchlist_manager)
    await decision_generator.start()

    # Phase 4: outcome resolution + calibration.
    # Rehydrate from the audit log before live feeds start: resolved history
    # feeds the calibration engine; still-unresolved proposals are re-tracked
    # and caught up against recent tick history so restarts don't orphan them.
    calibration_settings = CalibrationSettings()
    resolver = OutcomeResolver(bus, modes=mode_controller, settings=calibration_settings)
    calibration_engine = CalibrationEngine(bus, settings=calibration_settings)
    gate_tracker = GateTracker(bus, calibration_engine, settings=calibration_settings)

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
        for e in await store.recent([EventType.SIGNAL_CREATED.value], limit=500)
        if e.source == "rss_news_feed"
        and (sid := e.payload.get("provenance", {}).get("source_id"))
    }
    news_feed = NewsFeed(bus, initial_seen=seen_links, watchlist=watchlist_manager)
    news_task = asyncio.create_task(news_feed.run(), name="news_feed")

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

    logger.info("gateway.ready")
    yield  # ← app serves requests here

    logger.info("gateway.shutting_down")

    for task in (feed_task, equity_task, news_task):
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
