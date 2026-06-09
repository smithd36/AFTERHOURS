"""Deterministic sizing tests — most critical unit in the risk layer."""

from decimal import Decimal

import pytest

from risk.sizing import deterministic_size


def test_basic_sizing() -> None:
    size = deterministic_size(
        portfolio_value=Decimal("10000"),
        max_trade_loss_pct=0.02,
        stop_loss_pct=0.03,
        max_position_pct=0.05,
    )
    # risk_amount = 200; stop_distance = 0.03; raw = 6666.67; max = 500; result = 500
    assert size == Decimal("500.00")


def test_raw_wins_when_below_max() -> None:
    size = deterministic_size(
        portfolio_value=Decimal("10000"),
        max_trade_loss_pct=0.001,
        stop_loss_pct=0.05,
        max_position_pct=0.50,
    )
    # risk_amount = 10; stop = 0.05; raw = 200; max = 5000; raw wins
    assert size == Decimal("200.00")


def test_zero_portfolio() -> None:
    size = deterministic_size(
        portfolio_value=Decimal("0"),
        max_trade_loss_pct=0.02,
        stop_loss_pct=0.03,
        max_position_pct=0.05,
    )
    assert size == Decimal("0.00")


def test_two_decimal_precision() -> None:
    size = deterministic_size(
        portfolio_value=Decimal("7777.77"),
        max_trade_loss_pct=0.02,
        stop_loss_pct=0.03,
        max_position_pct=0.05,
    )
    assert size == size.quantize(Decimal("0.01"))
