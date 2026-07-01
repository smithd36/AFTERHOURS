"""PaperExecutor tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from core.bus import InMemoryEventStore, InProcessBus
from core.mode import ModeController
from core.schemas.events import AutonomyMode, EventEnvelope, EventType
from portfolio.executor import HaltedError, PaperExecutor, StaleDecisionError
from portfolio.ledger import Portfolio
from portfolio.settings import PortfolioSettings


@pytest.fixture
async def bus() -> InProcessBus:
    return InProcessBus(store=InMemoryEventStore())


@pytest.fixture
async def portfolio(bus: InProcessBus) -> Portfolio:
    p = Portfolio(bus)
    await p.start()
    return p


def _tick(
    instrument: str, price: str, event_time: datetime | None = None
) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.MARKET_TICK,
        source="test",
        event_time=event_time or datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={"instrument": instrument, "price": price, "volume": "1"},
    )


def _approved(
    instrument: str = "BTC-USD", size_usd: str = "500", event_time: datetime | None = None
) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.DECISION_APPROVED,
        source="test",
        event_time=event_time or datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={
            "id": str(uuid4()),
            "proposal": {"instrument": instrument, "side": "long", "size_usd": size_usd},
            "risk": {"stop_price": None, "rejection_reasons": []},
            "status": "approved",
        },
    )


async def test_paper_mode_auto_fills(bus: InProcessBus, portfolio: Portfolio) -> None:
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    await bus.publish(_approved("BTC-USD", "500"))
    assert len(fills) == 1
    assert fills[0].payload["action"] == "open"

    await executor.stop()


async def test_sub_cent_fill_price_and_quantity(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A sub-cent instrument fills at a non-zero price with a sane quantity."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("SHIB-USD", "0.00002"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    await bus.publish(_approved("SHIB-USD", "100"))
    assert len(fills) == 1
    fill_price = Decimal(fills[0].payload["fill_price"])
    quantity = Decimal(fills[0].payload["quantity"])
    assert fill_price > 0  # not collapsed to 0.00
    # $100 at ~$0.00002 buys ~5,000,000 units, not a garbage figure.
    assert quantity > Decimal(4_000_000)
    assert quantity < Decimal(6_000_000)

    await executor.stop()


async def test_open_carries_client_order_id_keyed_on_decision(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """The decision → order → fill chain carries a deterministic client_order_id."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    submitted: list[EventEnvelope] = []
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_SUBMITTED, lambda e: submitted.append(e))
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    env = _approved("BTC-USD", "500")
    decision_id = env.payload["id"]
    await bus.publish(env)

    expected = f"{decision_id}:open"
    assert len(submitted) == 1
    assert submitted[0].payload["client_order_id"] == expected
    assert submitted[0].payload["intent"] == "open"
    assert len(fills) == 1
    assert fills[0].payload["client_order_id"] == expected
    # Fill ties back to its idempotent order.
    assert fills[0].payload["fill"]["order_id"] == expected

    await executor.stop()


async def test_duplicate_approval_fills_once(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A re-delivered approval (same decision id) must not produce a second fill."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    env = _approved("BTC-USD", "500")
    await bus.publish(env)
    await bus.publish(env)  # exact re-delivery — same client_order_id

    assert len(fills) == 1  # idempotency rejected the duplicate

    await executor.stop()


async def test_close_carries_client_order_id(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Closing fills carry a distinct close-intent client_order_id for attribution."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    env = _approved("BTC-USD", "500")
    decision_id = env.payload["id"]
    await bus.publish(env)

    closes: list[EventEnvelope] = []
    await bus.subscribe(
        EventType.ORDER_FILLED,
        lambda e: closes.append(e) if e.payload["action"] == "close" else None,
    )

    ok = await executor.close_position("BTC-USD")
    assert ok is True
    assert len(closes) == 1
    assert closes[0].payload["client_order_id"] == f"{decision_id}:close"

    await executor.stop()


def _thesis_invalidated(
    instrument: str, reason: str = "expired", event_time: datetime | None = None
) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.THESIS_INVALIDATED,
        source="test",
        event_time=event_time or datetime.now(UTC),
        ingest_time=datetime.now(UTC),
        payload={"thesis_id": str(uuid4()), "reason": reason, "instrument": instrument},
    )


async def test_thesis_invalidation_closes_position(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """An expired/invalidated thesis flattens the instrument's open position."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    await bus.publish(_approved("BTC-USD", "500"))
    assert "BTC-USD" in portfolio.positions

    closes: list[EventEnvelope] = []
    await bus.subscribe(
        EventType.ORDER_FILLED,
        lambda e: closes.append(e) if e.payload["action"] == "close" else None,
    )

    await bus.publish(_thesis_invalidated("BTC-USD"))
    assert "BTC-USD" not in portfolio.positions
    assert len(closes) == 1
    assert closes[0].payload["action"] == "close"

    await executor.stop()


async def test_thesis_invalidation_no_position_is_noop(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Invalidating a thesis for an instrument we don't hold emits no fill."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    await bus.publish(_thesis_invalidated("ETH-USD"))
    assert fills == []

    await executor.stop()


async def test_invalidation_without_price_defers_then_closes_on_next_tick(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A thesis death with no current price (e.g. equity after-hours) must not
    orphan the position: the close is deferred and fills on the next tick."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    # Open, then drop the mark so close_position can't fill (no price).
    await bus.publish(_tick("AAPL", "200"))
    await bus.publish(_approved("AAPL", "500"))
    assert "AAPL" in portfolio.positions
    portfolio._prices.pop("AAPL")  # simulate a stale book with no live mark

    closes: list[EventEnvelope] = []
    await bus.subscribe(
        EventType.ORDER_FILLED,
        lambda e: closes.append(e) if e.payload["action"] == "close" else None,
    )

    await bus.publish(_thesis_invalidated("AAPL"))
    assert "AAPL" in portfolio.positions  # deferred, not dropped
    assert closes == []

    # Next tick supplies a price → the deferred close fills.
    await bus.publish(_tick("AAPL", "199"))
    assert "AAPL" not in portfolio.positions
    assert len(closes) == 1

    await executor.stop()


# Saturday 14:00 ET (market closed); 2026-06-29 is a Monday.
_MARKET_CLOSED = datetime(2026, 6, 27, 18, 0, tzinfo=UTC)


async def test_equity_close_deferred_when_market_closed(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A thesis death on an equity during a closed session must not fill at the
    stale last price: the close is deferred and fills on the next tick (the open).
    A price is available throughout, so this isolates the market-closed defer from
    the existing no-price defer."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("AAPL", "200"))
    await bus.publish(_approved("AAPL", "500"))
    assert "AAPL" in portfolio.positions

    closes: list[EventEnvelope] = []
    await bus.subscribe(
        EventType.ORDER_FILLED,
        lambda e: closes.append(e) if e.payload["action"] == "close" else None,
    )

    # Invalidation lands on a Saturday: defer despite the live mark.
    await bus.publish(_thesis_invalidated("AAPL", event_time=_MARKET_CLOSED))
    assert "AAPL" in portfolio.positions
    assert closes == []

    # A later tick (market open) fills the deferred close.
    await bus.publish(_tick("AAPL", "199"))
    assert "AAPL" not in portfolio.positions
    assert len(closes) == 1

    await executor.stop()


async def test_crypto_close_not_deferred_off_hours(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Crypto trades 24/7, so a thesis death closes immediately whatever the clock."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    await bus.publish(_approved("BTC-USD", "500"))
    assert "BTC-USD" in portfolio.positions

    closes: list[EventEnvelope] = []
    await bus.subscribe(
        EventType.ORDER_FILLED,
        lambda e: closes.append(e) if e.payload["action"] == "close" else None,
    )

    await bus.publish(_thesis_invalidated("BTC-USD", event_time=_MARKET_CLOSED))
    assert "BTC-USD" not in portfolio.positions
    assert len(closes) == 1

    await executor.stop()


async def test_reconcile_orphans_closes_dead_thesis_positions(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Startup reconcile flattens a position whose thesis is already dead."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.PAPER)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    await bus.publish(_approved("BTC-USD", "500"))
    assert "BTC-USD" in portfolio.positions

    closes: list[EventEnvelope] = []
    await bus.subscribe(
        EventType.ORDER_FILLED,
        lambda e: closes.append(e) if e.payload["action"] == "close" else None,
    )

    await executor.reconcile_orphans(["BTC-USD"], datetime.now(UTC))
    assert "BTC-USD" not in portfolio.positions
    assert len(closes) == 1

    await executor.stop()


async def test_rehydrate_pending_reparks_and_is_executable(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A non-terminal approval is re-parked on restart and stays executable."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    now = datetime.now(UTC)
    env = _approved("BTC-USD", "500", event_time=now)
    decision_id = env.payload["id"]

    await executor.rehydrate_pending([env], terminal_ids=set(), now=now)
    assert len(executor.pending_decisions) == 1
    assert executor.pending_decisions[0]["id"] == decision_id

    await executor.start()
    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))
    assert await executor.execute(decision_id) is True
    assert len(fills) == 1

    await executor.stop()


async def test_rehydrate_pending_skips_terminal_approvals(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """An approval that already filled/rejected/expired is not re-parked."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    now = datetime.now(UTC)
    env = _approved("BTC-USD", "500", event_time=now)
    decision_id = env.payload["id"]

    await executor.rehydrate_pending([env], terminal_ids={decision_id}, now=now)
    assert executor.pending_decisions == []


async def test_rehydrate_pending_expires_stale_instead_of_reparking(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """An approval already past its TTL is expired (audited), not re-parked."""
    settings = PortfolioSettings(pending_ttl_seconds=60)
    executor = PaperExecutor(
        bus, portfolio, initial_mode=AutonomyMode.ASSISTED, settings=settings
    )
    expired: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_EXPIRED, lambda e: expired.append(e))

    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    env = _approved("BTC-USD", "500", event_time=base)
    decision_id = env.payload["id"]

    await executor.rehydrate_pending(
        [env], terminal_ids=set(), now=base + timedelta(seconds=61)
    )
    assert executor.pending_decisions == []
    assert len(expired) == 1
    assert expired[0].payload["decision_id"] == decision_id
    assert expired[0].payload["reason"] == "ttl_expired_on_restart"


async def test_observe_mode_ignores(bus: InProcessBus, portfolio: Portfolio) -> None:
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.OBSERVE)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    await bus.publish(_approved("BTC-USD", "500"))
    assert len(fills) == 0

    await executor.stop()


async def test_assisted_mode_parks(bus: InProcessBus, portfolio: Portfolio) -> None:
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    env = _approved("BTC-USD", "500")
    decision_id = env.payload["id"]
    await bus.publish(env)

    assert len(fills) == 0
    assert len(executor.pending_decisions) == 1

    ok = await executor.execute(decision_id)
    assert ok is True
    assert len(fills) == 1

    await executor.stop()


async def test_halt_expires_pending_and_blocks_execution(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """The kill switch must flush the queue and refuse any later execute()."""
    modes = ModeController(bus, initial=AutonomyMode.ASSISTED)
    executor = PaperExecutor(bus, portfolio, modes=modes)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    expired: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))
    await bus.subscribe(EventType.DECISION_EXPIRED, lambda e: expired.append(e))

    env = _approved("BTC-USD", "500")
    decision_id = env.payload["id"]
    await bus.publish(env)
    assert len(executor.pending_decisions) == 1

    # Kill switch fires through the controller (forces OBSERVE, publishes risk.halt).
    await modes.halt()

    # Queue is flushed with an audited decision.expired carrying the decision id.
    assert len(executor.pending_decisions) == 0
    assert len(expired) == 1
    assert expired[0].payload["decision_id"] == decision_id
    assert str(expired[0].correlation_id) == decision_id

    # The parked decision can no longer be executed — kill-switch bypass closed.
    with pytest.raises(HaltedError):
        await executor.execute(decision_id)
    assert len(fills) == 0

    await executor.stop()


async def test_mode_demotion_expires_pending(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Demotion below ASSISTED expires parked decisions even without a halt."""
    modes = ModeController(bus, initial=AutonomyMode.ASSISTED)
    executor = PaperExecutor(bus, portfolio, modes=modes)
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    expired: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_EXPIRED, lambda e: expired.append(e))

    await bus.publish(_approved("BTC-USD", "500"))
    assert len(executor.pending_decisions) == 1

    await modes.set(AutonomyMode.OBSERVE)
    assert len(executor.pending_decisions) == 0
    assert len(expired) == 1

    await executor.stop()


async def test_execute_refused_in_observe(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """execute() refuses outright when authority is below ASSISTED."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.OBSERVE)
    await executor.start()

    with pytest.raises(HaltedError):
        await executor.execute("does-not-matter")

    await executor.stop()


async def test_pending_decision_expires_after_ttl(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """A parked decision past its TTL is swept (event-clock driven) and audited."""
    settings = PortfolioSettings(pending_ttl_seconds=60)
    executor = PaperExecutor(
        bus, portfolio, initial_mode=AutonomyMode.ASSISTED, settings=settings
    )
    await executor.start()

    expired: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_EXPIRED, lambda e: expired.append(e))

    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    env = _approved("BTC-USD", "500", event_time=base)
    decision_id = env.payload["id"]
    await bus.publish(env)
    assert len(executor.pending_decisions) == 1

    # A tick 61s later (> 60s TTL) drives the sweep on the event clock.
    await bus.publish(_tick("BTC-USD", "50000", event_time=base + timedelta(seconds=61)))

    assert len(executor.pending_decisions) == 0
    assert len(expired) == 1
    assert expired[0].payload["decision_id"] == decision_id
    assert expired[0].payload["reason"] == "ttl_expired"

    await executor.stop()


async def test_execute_revalidates_and_refreshes_stop(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """execute() fills the re-validated payload (fresh stop), not the stale parked one."""
    def validator(payload: dict[str, Any], now: datetime) -> tuple[bool, dict[str, Any], list[str]]:
        # Approve, but with a freshly computed stop the parked payload never had.
        refreshed = dict(payload)
        refreshed["risk"] = {**payload.get("risk", {}), "stop_price": "49000"}
        return (True, refreshed, [])

    executor = PaperExecutor(
        bus, portfolio, initial_mode=AutonomyMode.ASSISTED, validator=validator
    )
    await executor.start()

    await bus.publish(_tick("BTC-USD", "50000"))
    fills: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))

    env = _approved("BTC-USD", "500")  # parked payload has stop_price=None
    decision_id = env.payload["id"]
    await bus.publish(env)

    assert await executor.execute(decision_id) is True
    assert len(fills) == 1
    assert fills[0].payload["stop_price"] == "49000"  # recomputed, not the stale None

    await executor.stop()


async def test_execute_expires_on_failed_revalidation(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """If re-validation fails at execute time, nothing fills and the decision expires."""
    def validator(payload: dict[str, Any], now: datetime) -> tuple[bool, dict[str, Any], list[str]]:
        return (False, {}, ["position_exists: already holding BTC-USD"])

    executor = PaperExecutor(
        bus, portfolio, initial_mode=AutonomyMode.ASSISTED, validator=validator
    )
    await executor.start()

    fills: list[EventEnvelope] = []
    expired: list[EventEnvelope] = []
    await bus.subscribe(EventType.ORDER_FILLED, lambda e: fills.append(e))
    await bus.subscribe(EventType.DECISION_EXPIRED, lambda e: expired.append(e))

    env = _approved("BTC-USD", "500")
    decision_id = env.payload["id"]
    await bus.publish(env)

    with pytest.raises(StaleDecisionError):
        await executor.execute(decision_id)

    assert len(fills) == 0
    assert len(expired) == 1
    assert "revalidation_failed" in expired[0].payload["reason"]

    await executor.stop()


async def test_operator_reject_is_audited(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Rejecting a parked decision emits an audited decision.rejected with the reason."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    await executor.start()

    rejected: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_REJECTED, lambda e: rejected.append(e))

    env = _approved("BTC-USD", "500")
    decision_id = env.payload["id"]
    await bus.publish(env)
    assert len(executor.pending_decisions) == 1

    ok = await executor.reject(decision_id, reason="thesis no longer holds")
    assert ok is True
    assert len(executor.pending_decisions) == 0

    assert len(rejected) == 1
    payload = rejected[0].payload
    assert payload["id"] == decision_id            # decision_store tracker keys on this
    assert payload["status"] == "rejected"
    human = payload["human"]
    assert human["actor"] == "operator"
    assert human["action"] == "rejected"
    assert human["note"] == "thesis no longer holds"   # the training-gold signal
    assert str(rejected[0].correlation_id) == decision_id

    await executor.stop()


async def test_reject_unknown_decision_returns_false(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    await executor.start()

    assert await executor.reject("not-in-queue", reason="x") is False

    await executor.stop()


async def test_shutdown_expires_pending(
    bus: InProcessBus, portfolio: Portfolio
) -> None:
    """Restart/shutdown must not silently drop the queue — it emits decision.expired."""
    executor = PaperExecutor(bus, portfolio, initial_mode=AutonomyMode.ASSISTED)
    await executor.start()

    expired: list[EventEnvelope] = []
    await bus.subscribe(EventType.DECISION_EXPIRED, lambda e: expired.append(e))

    await bus.publish(_approved("BTC-USD", "500"))
    assert len(executor.pending_decisions) == 1

    await executor.stop()  # simulates graceful restart

    assert len(expired) == 1
    assert expired[0].payload["reason"] == "shutdown"
