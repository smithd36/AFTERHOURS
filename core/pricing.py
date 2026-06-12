"""Magnitude-aware price quantization.

A single hard-coded tick (e.g. cents) cannot serve a watchlist that spans
BTC at ~$60,000 and SHIB at ~$0.00002: ``Decimal.quantize(Decimal("0.01"))``
collapses every sub-cent price to ``0.00``, which yields a zero stop that can
never trigger and a divide-by-rounded-price sizing blow-up.

We quantize prices to a fixed number of *significant figures* instead, so the
effective tick scales with the price. This approximates per-instrument tick
size without carrying venue metadata, and never rounds a positive price to
zero.
"""

from __future__ import annotations

from decimal import Decimal

# Eight significant figures comfortably covers both five-figure majors and
# sub-cent meme coins while keeping stored prices tidy.
PRICE_SIG_FIGS = 8


def quantize_price(price: Decimal, sig_figs: int = PRICE_SIG_FIGS) -> Decimal:
    """Round ``price`` to ``sig_figs`` significant figures.

    Zero passes through unchanged; sign is preserved. Unlike cent rounding,
    a non-zero price never collapses to zero, so sub-cent instruments keep a
    usable stop and a correct quantity.
    """
    if price == 0:
        return price
    # ``adjusted()`` is the exponent of the most significant digit; place the
    # quantum ``sig_figs - 1`` decades below it.
    quantum = Decimal(1).scaleb(price.adjusted() - (sig_figs - 1))
    return price.quantize(quantum)
