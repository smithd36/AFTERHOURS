"""
Backtest engine — replays recorded source events through the live pipeline.

Replay rules (docs/phase4-plan.md, workstream C):

  * Only *source* topics are replayed: `market.tick` and `signal.created`
    exactly as recorded (including historical price-alert signals).
    Derived events — theses, decisions, verdicts, fills, resolutions —
    regenerate by running the real components on an isolated in-memory
    bus; replaying them too would double-count.
  * The signal/feed generators (Kraken, RSS, price alerts) are NOT run:
    their outputs are the recorded inputs.
  * Point-in-time correctness: every pipeline component derives its
    financial clock from the triggering envelope's `event_time` (and the
    thesis window from the recorded `ingest_time`, preserving the actual
    information-arrival order), so no wall clock leaks into replay.
  * LLM calls go through CachingProvider — `replay` mode is deterministic
    and free (cache misses skip that thesis/decision, logged); `live`
    mode calls the configured provider and records for future replays.

The thesis invalidator is wall-clock paced and is intentionally excluded;
decisions still resolve via their horizon, so calibration is unaffected
(invalidation-triggered early resolution simply doesn't occur in replay).
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from calibration import CalibrationEngine, CalibrationSettings, OutcomeResolver
from core.bus import InMemoryEventStore, InProcessBus
from core.mode import ModeController
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio import PaperExecutor, Portfolio
from portfolio.settings import PortfolioSettings
from reasoning.decision import DecisionGenerator
from reasoning.llm.base import LLMProvider
from reasoning.thesis import ThesisGenerator
from reasoning.thesis.settings import ThesisSettings
from risk import RiskEngine
from risk.settings import RiskSettings

logger = structlog.get_logger(__name__)

SOURCE_TOPICS: tuple[str, ...] = (
    EventType.MARKET_TICK.value,
    EventType.SIGNAL_CREATED.value,
)

# Topics the pipeline is expected to regenerate during replay.
_GENERATED_TOPICS: tuple[str, ...] = (
    EventType.THESIS_CREATED.value,
    EventType.DECISION_PROPOSED.value,
    EventType.DECISION_APPROVED.value,
    EventType.DECISION_REJECTED.value,
    EventType.ORDER_FILLED.value,
    EventType.RISK_LIMIT_BREACHED.value,
    EventType.DECISION_RESOLVED.value,
)


class BacktestRunner:
    def __init__(
        self,
        source_events: Sequence[EventEnvelope],
        provider: LLMProvider,
        mode: AutonomyMode = AutonomyMode.PAPER,
        thesis_settings: ThesisSettings | None = None,
        risk_settings: RiskSettings | None = None,
        portfolio_settings: PortfolioSettings | None = None,
        calibration_settings: CalibrationSettings | None = None,
    ) -> None:
        self._source_events = source_events
        self._provider = provider
        self._mode = mode
        self._thesis_settings = thesis_settings or ThesisSettings()
        self._risk_settings = risk_settings or RiskSettings()
        self._portfolio_settings = portfolio_settings or PortfolioSettings()
        self._calibration_settings = calibration_settings or CalibrationSettings()

    async def run(self) -> dict[str, Any]:
        store = InMemoryEventStore()
        bus = InProcessBus(store)

        # One mode source of truth, fixed for the whole replay (backtests don't
        # change mode mid-run); every component reads it instead of caching.
        mode_controller = ModeController(bus, initial=self._mode)
        portfolio = Portfolio(bus, settings=self._portfolio_settings)
        risk_engine = RiskEngine(
            bus, portfolio, modes=mode_controller, settings=self._risk_settings
        )
        executor = PaperExecutor(
            bus, portfolio, modes=mode_controller, settings=self._portfolio_settings
        )
        thesis_generator = ThesisGenerator(bus, self._provider, settings=self._thesis_settings)
        decision_generator = DecisionGenerator(bus, self._provider)
        resolver = OutcomeResolver(
            bus, modes=mode_controller, settings=self._calibration_settings
        )
        calibration = CalibrationEngine(bus, settings=self._calibration_settings)

        components = (
            portfolio,
            risk_engine,
            executor,
            thesis_generator,
            decision_generator,
            resolver,
            calibration,
        )
        for component in components:
            await component.start()

        generated: Counter[str] = Counter()

        async def _count(envelope: EventEnvelope) -> None:
            generated[envelope.event_type] += 1

        for topic in _GENERATED_TOPICS:
            await bus.subscribe(topic, _count)

        replayed: Counter[str] = Counter()
        equity_curve: list[tuple[str, str]] = []
        last_total: str | None = None

        for envelope in self._source_events:
            replayed[envelope.event_type] += 1
            await bus.publish(envelope)
            if envelope.event_type == EventType.MARKET_TICK.value:
                total = str(portfolio.total_value)
                if total != last_total:
                    equity_curve.append((envelope.event_time.isoformat(), total))
                    last_total = total

        for component in reversed(components):
            await component.stop()
        await bus.close()

        event_times = [e.event_time for e in self._source_events]
        return {
            "run_id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "mode": self._mode.value,
            "window": {
                "from": min(event_times).isoformat() if event_times else None,
                "to": max(event_times).isoformat() if event_times else None,
            },
            "replayed": dict(replayed),
            "generated": dict(generated),
            "unresolved_decisions": resolver.pending_count,
            "calibration": calibration.report(),
            "portfolio": portfolio.snapshot(),
            "equity_curve": equity_curve,
            "settings": {
                "thesis": self._thesis_settings.model_dump(),
                "risk": self._risk_settings.model_dump(),
                "portfolio": self._portfolio_settings.model_dump(mode="json"),
                "calibration": self._calibration_settings.model_dump(),
            },
        }


def write_artifact(report: dict[str, Any], out_dir: str | Path) -> Path:
    """Persist the run report as JSON; returns the artifact path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"run_{stamp}_{report['run_id'][:8]}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("backtest.artifact_written", path=str(path))
    return path
