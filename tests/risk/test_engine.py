"""RiskEngine integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.schemas.decision import Side
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.ledger import Portfolio
from risk.engine import RiskEngine


def _proposed_envelope(instrument: str = "BTC-USD") -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.DECISION_PROPOSED,
        source="test",
        event_time=datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={
            "id": str(uuid4()),
            "proposal": {"instrument": instrument, "side": "long", "size_usd": "0"},
            "reasoning": "test",
            "confidence": 0.7,
            "status": "proposed",
        },
    )


def _proposed_at(instrument: str, event_time: datetime) -> EventEnvelope:
    env = _proposed_envelope(instrument)
    return env.model_copy(update={"event_time": event_time})


async def _realize_loss(bus: InProcessBus, instrument: str, event_time: datetime) -> None:
    """Open and close a position at a loss on `event_time`'s UTC day (~$600 loss)."""
    for action, price in (("open", "1000"), ("close", "400")):
        await bus.publish(EventEnvelope(
            event_type=EventType.ORDER_FILLED,
            source="test",
            event_time=event_time,
            ingest_time=datetime.now(UTC),
            payload={
                "instrument": instrument, "action": action, "side": "long",
                "fill_price": price, "quantity": "1", "cost_usd": "1000",
                "fee": "0", "stop_price": None, "decision_id": "seed",
            },
        ))


def _tick_envelope(instrument: str, price: str) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="test",
        event_time=datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={"instrument": instrument, "price": price, "volume": "1"},
    )


@pytest.fixture
async def bus() -> InProcessBus:
    b = InProcessBus(store=InMemoryEventStore())
    return b


@pytest.fixture
async def portfolio(bus: InProcessBus) -> Portfolio:
    p = Portfolio(bus)
    await p.start()
    return p


async def test_observe_mode_rejects_all(bus: InProcessBus, portfolio: Portfolio) -> None:
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.OBSERVE)
    await engine.start()

    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    await bus.publish(_proposed_envelope())
    assert len(rejected) == 1
    reasons = rejected[0].payload["risk"]["rejection_reasons"]
    assert any("observe_mode" in r for r in reasons)

    await engine.stop()


async def test_paper_mode_approves_with_price(bus: InProcessBus, portfolio: Portfolio) -> None:
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    # Seed price
    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))

    assert len(approved) == 1
    size = Decimal(approved[0].payload["proposal"]["size_usd"])
    assert size > 0

    await engine.stop()


async def test_sub_cent_instrument_gets_nonzero_stop(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A SHIB-class price must yield a real stop, not 0.00 from cent rounding."""
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    await bus.publish(_tick_envelope("SHIB-USD", "0.00002345"))

    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_envelope("SHIB-USD"))

    assert len(approved) == 1
    stop = Decimal(approved[0].payload["risk"]["stop_price"])
    assert stop > 0
    assert stop < Decimal("0.00002345")  # long stop sits below entry

    await engine.stop()


async def test_max_positions_rejected(bus: InProcessBus, portfolio: Portfolio) -> None:
    from risk.settings import RiskSettings
    settings = RiskSettings(max_open_positions=0)  # artificially 0
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER, settings=settings)
    await engine.start()

    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))
    assert len(rejected) == 1
    reasons = rejected[0].payload["risk"]["rejection_reasons"]
    assert any("max_open_positions" in r for r in reasons)

    await engine.stop()


async def test_low_cash_rejects_below_min_trade_size(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """When cash is nearly depleted, a trade that can't be afforded is rejected
    rather than driving the ledger negative."""
    from portfolio.models import Position

    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    # Simulate a book whose cash is almost gone but whose total_value (cash +
    # marked positions) is still large enough for max_position_pct to size a
    # trade well above the cash on hand.
    portfolio.cash = Decimal("5.00")
    portfolio.positions["ETH-USD"] = Position(
        instrument="ETH-USD", side=Side.LONG, entry_price=Decimal("1000"),
        quantity=Decimal("9"), current_price=Decimal("1000"),
        stop_price=None, decision_id="seed",
    )
    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))
    assert len(rejected) == 1
    reasons = rejected[0].payload["risk"]["rejection_reasons"]
    assert any("insufficient_cash" in r for r in reasons)

    await engine.stop()


async def test_size_capped_at_affordable_cash(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """An approved size never exceeds the cash on hand, less the buffer, so the
    ledger cannot go negative when the executor deducts size + fee."""
    from portfolio.models import Position

    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    # total_value ~ $10k (so max_position_pct would size ~$500) but only $300
    # cash on hand → the affordability cap must bind below the pct cap.
    portfolio.cash = Decimal("300.00")
    portfolio.positions["ETH-USD"] = Position(
        instrument="ETH-USD", side=Side.LONG, entry_price=Decimal("1000"),
        quantity=Decimal("9.7"), current_price=Decimal("1000"),
        stop_price=None, decision_id="seed",
    )
    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))
    assert len(approved) == 1
    size = Decimal(approved[0].payload["proposal"]["size_usd"])
    assert size <= portfolio.cash  # affordable, with fee/slippage headroom to spare

    await engine.stop()


async def test_daily_loss_breaker_trips_same_day(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A loss exceeding max_daily_loss_pct on the proposal's own day blocks entry."""
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    day = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    await _realize_loss(bus, "ETH-USD", day)  # ~6% of a 10k book
    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    await bus.publish(_proposed_at("BTC-USD", day))
    assert len(rejected) == 1
    reasons = rejected[0].payload["risk"]["rejection_reasons"]
    assert any("daily_loss_limit" in r for r in reasons)

    await engine.stop()


async def test_daily_loss_breaker_resets_next_day(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Yesterday's realized loss must not block a fresh-day entry (the reported bug)."""
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    yesterday = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
    today = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
    await _realize_loss(bus, "ETH-USD", yesterday)
    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_at("BTC-USD", today))
    assert len(approved) == 1  # not blocked by yesterday's loss

    await engine.stop()


async def test_no_tick_data_rejected_no_stop(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A proposal with no tick data (no computable stop) is rejected, not approved."""
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    approved: list[EventEnvelope] = []
    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    # No tick seeded for SOL-USD → no stop can be computed.
    await bus.publish(_proposed_envelope("SOL-USD"))

    assert len(approved) == 0
    assert len(rejected) == 1
    reasons = rejected[0].payload["risk"]["rejection_reasons"]
    assert any("no_stop_price" in r for r in reasons)

    await engine.stop()


async def test_approved_decision_always_has_stop(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Every approved decision carries a non-null stop_price by construction."""
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await engine.start()

    await bus.publish(_tick_envelope("BTC-USD", "50000"))
    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))
    assert len(approved) == 1
    assert approved[0].payload["risk"]["stop_price"] is not None

    await engine.stop()


async def test_mode_change_via_event(bus: InProcessBus, portfolio: Portfolio) -> None:
    engine = RiskEngine(bus, portfolio, initial_mode=AutonomyMode.OBSERVE)
    await engine.start()

    # Change to PAPER via event
    now = datetime.now(UTC)
    await bus.publish(EventEnvelope(
        event_type=EventType.SYSTEM_MODE_CHANGED,
        source="test",
        event_time=now,
        ingest_time=now,
        payload={"from_mode": "observe", "to_mode": "paper", "actor": "test", "reason": ""},
    ))

    await bus.publish(_tick_envelope("BTC-USD", "50000"))

    approved: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_APPROVED, lambda e: approved.append(e))

    await bus.publish(_proposed_envelope("BTC-USD"))
    assert len(approved) == 1

    await engine.stop()
