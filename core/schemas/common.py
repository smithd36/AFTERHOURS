"""
Shared primitives: Instrument, Provenance, Money.
These are the atoms everything else is built from.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class Market(str, Enum):
    CRYPTO = "crypto"
    EQUITY = "equity"


class Instrument(BaseModel):
    """
    Canonical identity for a tradable asset across venues.
    BTC-USD on Coinbase and BTC-USD on Kraken are the same Instrument
    with two venue_symbols entries — never treat them as separate assets.
    """

    symbol: str  # canonical: "BTC-USD"
    market: Market
    base_asset: str  # "BTC"
    quote_asset: str  # "USD"
    venue_symbols: dict[str, str] = Field(default_factory=dict)  # venue_id -> venue_symbol


class Provenance(BaseModel):
    """
    Every datum carries where it came from and when.
    Two clocks: event_time (market) vs ingest_time (us).
    Point-in-time correctness in the feature store and backtester
    must use event_time; never use ingest_time for financial logic.
    """

    source: str  # e.g. "coinbase_ws", "cryptopanic_api", "finnhub_rest"
    source_id: Optional[str] = None  # vendor's own dedup key if present
    event_time: datetime  # when it happened in the market / source (UTC)
    ingest_time: datetime  # when we received + processed it (UTC)
    url: Optional[str] = None  # canonical link to the source document


class Money(BaseModel):
    """Exact decimal representation of a monetary amount."""

    amount: Decimal
    currency: str  # ISO 4217 or crypto ticker, e.g. "USD", "BTC"
