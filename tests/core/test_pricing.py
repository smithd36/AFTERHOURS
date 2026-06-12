"""Tests for magnitude-aware price quantization."""

from __future__ import annotations

from decimal import Decimal

from core.pricing import quantize_price


def test_sub_cent_price_survives() -> None:
    """A SHIB-class price must not collapse to zero (the bug)."""
    out = quantize_price(Decimal("0.00002345678"))
    assert out > 0
    assert out == Decimal("0.000023456780")


def test_majors_keep_at_least_cent_precision() -> None:
    """Five-figure prices round to eight sig figs (sub-cent here), not coarser."""
    assert quantize_price(Decimal("60000.123456789")) == Decimal("60000.123")


def test_zero_passes_through() -> None:
    assert quantize_price(Decimal("0")) == Decimal("0")


def test_sign_preserved() -> None:
    assert quantize_price(Decimal("-0.00002345678")) == Decimal("-0.000023456780")


def test_eight_significant_figures() -> None:
    # 9 significant digits in -> rounded to 8.
    assert quantize_price(Decimal("1.23456789")) == Decimal("1.2345679")
