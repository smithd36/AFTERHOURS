"""Order idempotency-key contract (PLANNING §2.5)."""

from __future__ import annotations

from core.schemas.decision import Order


def test_client_order_id_is_deterministic_and_keyed_on_decision() -> None:
    did = "11111111-1111-1111-1111-111111111111"
    assert Order.make_client_order_id(did, "open") == f"{did}:open"
    # Same inputs → same key (idempotent across retries / re-delivery).
    assert Order.make_client_order_id(did, "open") == Order.make_client_order_id(did, "open")


def test_open_and_close_keys_are_distinct() -> None:
    did = "22222222-2222-2222-2222-222222222222"
    assert Order.make_client_order_id(did, "open") != Order.make_client_order_id(did, "close")
