"""
BacktestRunner integration tests.

Replays a scripted event history (ticks + signals) through the real
pipeline — thesis → decision → risk → paper fill → outcome resolution →
calibration — with a scripted LLM provider. No network, no wall clock:
every timestamp asserted below is derived from replayed event_time.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from backtest import BacktestRunner
from calibration.settings import CalibrationSettings
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.settings import PortfolioSettings
from reasoning.llm import CachingProvider, JsonFileLLMCache
from reasoning.llm.base import LLMProvider, Message
from reasoning.thesis.settings import ThesisSettings
from risk.settings import RiskSettings

T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

THESIS_RESPONSE = json.dumps({
    "instrument": "BTC-USD",
    "summary": "BTC momentum building",
    "body": "Three converging signals.",
    "direction": "long",
    "confidence": 0.7,
    "invalidation_conditions": ["price below 95"],
    "time_horizon_hours": 6,
})

DECISION_RESPONSE = json.dumps({
    "side": "long",
    "time_horizon": "scalp",
    "reasoning": "Momentum continuation.",
    "evidence": [{"signal_id": str(uuid4()), "summary": "price alert", "stance": "supporting"}],
    "confidence": 0.7,
})


class ScriptedProvider(LLMProvider):
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, messages: list[Message], *, max_tokens: int = 1024) -> str:
        self.calls += 1
        return self._responses.pop(0)


def _tick(price: str, at: datetime, instrument: str = "BTC-USD") -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="kraken_feed",
        event_time=at,
        ingest_time=at,
        payload={"instrument": instrument, "price": price, "volume": "1"},
    )


def _signal(at: datetime, instrument: str = "BTC-USD") -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.SIGNAL_CREATED,
        source="price_alert_generator",
        event_time=at,
        ingest_time=at,
        payload={
            "id": str(uuid4()),
            "type": "price_alert",
            "instruments": [instrument],
            "provenance": {"event_time": at.isoformat(), "ingest_time": at.isoformat()},
            "payload": {"summary": f"{instrument} moved"},
        },
    )


def _scenario() -> list[EventEnvelope]:
    return [
        _tick("100", T0),                                   # seeds price for sizing/fill
        _signal(T0 + timedelta(seconds=1)),
        _signal(T0 + timedelta(seconds=2)),
        _signal(T0 + timedelta(seconds=3)),                 # 3rd signal → thesis → decision
        _tick("100", T0 + timedelta(seconds=4)),            # resolver entry price
        _tick("110", T0 + timedelta(minutes=31)),           # past scalp deadline → resolved
    ]


def _settings() -> dict:
    return {
        "thesis_settings": ThesisSettings(
            min_signals_to_trigger=3, signal_window_minutes=15, cooldown_minutes=60
        ),
        "risk_settings": RiskSettings(
            max_position_pct=0.05, max_trade_loss_pct=0.02, stop_loss_pct=0.03,
            max_open_positions=5, max_daily_loss_pct=0.05,
        ),
        "portfolio_settings": PortfolioSettings(
            initial_cash=Decimal("10000.00"), slippage_pct=0.001, fee_pct=0.001
        ),
        "calibration_settings": CalibrationSettings(horizon_scalp_minutes=30),
    }


async def test_paper_replay_end_to_end() -> None:
    provider = ScriptedProvider([THESIS_RESPONSE, DECISION_RESPONSE])
    runner = BacktestRunner(
        source_events=_scenario(),
        provider=provider,
        mode=AutonomyMode.PAPER,
        **_settings(),
    )
    report = await runner.run()

    assert report["replayed"] == {"market.tick": 3, "signal.created": 3}
    g = report["generated"]
    assert g["thesis.created"] == 1
    assert g["decision.proposed"] == 1
    assert g["decision.approved"] == 1
    assert g["order.filled"] == 1
    assert g["decision.resolved"] == 1
    assert provider.calls == 2

    # Long from 100 → 110: a hit at confidence 0.7 → ECE |0.7 − 1.0| = 0.3
    calib = report["calibration"]["overall"]
    assert calib["n"] == 1
    assert calib["ece"] == 0.3
    assert report["calibration"]["by_mode"].keys() == {"paper"}
    assert report["unresolved_decisions"] == 0

    # Position opened at ~100 and marked at 110 → equity above initial cash
    assert report["portfolio"]["open_positions"] == 1
    assert Decimal(report["portfolio"]["total_value"]) > Decimal("10000.00")

    # Equity curve timestamps come from replayed event_time, not the wall clock
    assert report["equity_curve"][0][0] == T0.isoformat()
    assert report["window"]["from"] == T0.isoformat()


async def test_observe_replay_produces_shadow_resolutions() -> None:
    provider = ScriptedProvider([THESIS_RESPONSE, DECISION_RESPONSE])
    runner = BacktestRunner(
        source_events=_scenario(),
        provider=provider,
        mode=AutonomyMode.OBSERVE,
        **_settings(),
    )
    report = await runner.run()

    g = report["generated"]
    assert g["decision.proposed"] == 1
    assert g["decision.rejected"] == 1          # shadow decision
    assert "order.filled" not in g              # nothing executes in OBSERVE
    assert g["decision.resolved"] == 1          # but it still gets scored
    assert report["calibration"]["by_mode"].keys() == {"observe"}
    assert report["portfolio"]["open_positions"] == 0


async def test_replay_llm_mode_skips_uncached_prompts(tmp_path) -> None:
    """Empty cache + no inner provider: the thesis is skipped, run completes."""
    provider = CachingProvider(JsonFileLLMCache(tmp_path / "cache.json"), inner=None)
    runner = BacktestRunner(
        source_events=_scenario(),
        provider=provider,
        mode=AutonomyMode.PAPER,
        **_settings(),
    )
    report = await runner.run()

    assert report["generated"] == {}            # LLM miss → no thesis → nothing downstream
    assert provider.misses == 1
    assert report["replayed"]["market.tick"] == 3


async def test_recorded_responses_make_replay_deterministic(tmp_path) -> None:
    """Record pass with a live-ish provider, then a pure replay reproduces it."""
    # Same recorded history for both runs — prompt hashes only match when
    # the replayed events (and thus signal ids) are identical.
    events = _scenario()
    cache_path = tmp_path / "cache.json"
    recording = CachingProvider(
        JsonFileLLMCache(cache_path),
        inner=ScriptedProvider([THESIS_RESPONSE, DECISION_RESPONSE]),
    )
    first = await BacktestRunner(
        source_events=events, provider=recording,
        mode=AutonomyMode.PAPER, **_settings(),
    ).run()

    replaying = CachingProvider(JsonFileLLMCache(cache_path), inner=None)
    second = await BacktestRunner(
        source_events=events, provider=replaying,
        mode=AutonomyMode.PAPER, **_settings(),
    ).run()

    assert replaying.misses == 0 and replaying.hits == 2
    assert second["generated"] == first["generated"]
    assert second["calibration"] == first["calibration"]
    assert second["portfolio"]["total_value"] == first["portfolio"]["total_value"]