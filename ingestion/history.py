"""
On-demand historical OHLC bars for the chart UI — a read-side pull, no bus, no
persistence (the same pull-first stance as analytics/discovery).

Market is inferred from the canonical symbol: a dash means crypto ("BTC-USD" →
Kraken public OHLC, no auth); anything else is an equity ("AAPL" → Alpaca bars,
reusing the EquityFeed data key). Both upstreams are normalized to the same
``Bar`` list (epoch-second timestamps, so the chart lib handles intraday and
daily uniformly).

A ``range`` (1D…1Y) maps to an interval + lookback: short ranges are intraday,
long ranges are daily — see ``RANGES``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ingestion.equity.settings import EquityFeedSettings
from ingestion.kraken.normalizer import canonical_to_kraken

_KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
_ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"


@dataclass(frozen=True)
class RangeSpec:
    kraken_interval: int  # Kraken OHLC interval, minutes (valid: 1,5,15,30,60,240,1440,…)
    alpaca_tf: str  # Alpaca timeframe string
    lookback_days: int  # how far back to request (Alpaca start bound)
    keep: int  # trim to the most-recent N bars (Kraken ignores our window)


# Short ranges are intraday, long ranges daily. `keep` is sized for 24/7 crypto;
# equities (shorter sessions) simply return fewer bars and aren't over-trimmed.
RANGES: dict[str, RangeSpec] = {
    "1D": RangeSpec(kraken_interval=5, alpaca_tf="5Min", lookback_days=1, keep=288),
    "1W": RangeSpec(kraken_interval=60, alpaca_tf="1Hour", lookback_days=7, keep=168),
    "1M": RangeSpec(kraken_interval=1440, alpaca_tf="1Day", lookback_days=31, keep=31),
    "3M": RangeSpec(kraken_interval=1440, alpaca_tf="1Day", lookback_days=93, keep=92),
    "1Y": RangeSpec(kraken_interval=1440, alpaca_tf="1Day", lookback_days=366, keep=366),
}
DEFAULT_RANGE = "3M"


@dataclass(frozen=True)
class Bar:
    t: int  # epoch seconds (UTC) — uniform for intraday and daily
    o: float
    h: float
    l: float  # noqa: E741 — OHLC convention; "l" is the low
    c: float
    v: float


class HistoryUnavailable(RuntimeError):
    """Upstream can't serve the bars (missing key, bad symbol, provider error)."""


def is_crypto(instrument: str) -> bool:
    """Canonical crypto symbols carry a quote suffix ("BTC-USD"); equities don't."""
    return "-" in instrument


def parse_kraken_ohlc(data: dict[str, Any]) -> list[Bar]:
    """Kraken result → bars. The pair key is Kraken's internal name, not ours;
    take the only non-"last" key. Rows: [time, o, h, l, c, vwap, volume, count]."""
    result = data.get("result") or {}
    rows = next((v for k, v in result.items() if k != "last"), None)
    if not isinstance(rows, list):
        return []
    return [
        Bar(t=int(r[0]), o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4]), v=float(r[6]))
        for r in rows
    ]


def parse_alpaca_bars(data: dict[str, Any]) -> list[Bar]:
    """Alpaca {"bars": [{t,o,h,l,c,v}]} → bars (``bars`` is null when empty).
    ``t`` is RFC3339 ("2026-06-17T13:30:00Z") → epoch seconds."""
    rows = data.get("bars") or []
    return [
        Bar(
            t=int(datetime.fromisoformat(str(b["t"])).timestamp()),
            o=float(b["o"]),
            h=float(b["h"]),
            l=float(b["l"]),
            c=float(b["c"]),
            v=float(b.get("v", 0)),
        )
        for b in rows
    ]


async def fetch_ohlc(
    instrument: str,
    *,
    range_key: str = DEFAULT_RANGE,
    settings: EquityFeedSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[Bar]:
    """OHLC for ``instrument`` over ``range_key`` (see RANGES), oldest→newest."""
    spec = RANGES.get(range_key) or RANGES[DEFAULT_RANGE]
    async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
        if is_crypto(instrument):
            bars = await _fetch_kraken(client, instrument, spec)
        else:
            bars = await _fetch_alpaca(client, instrument, spec, settings or EquityFeedSettings())
    return bars[-spec.keep :] if len(bars) > spec.keep else bars


async def _fetch_kraken(
    client: httpx.AsyncClient, instrument: str, spec: RangeSpec
) -> list[Bar]:
    try:
        resp = await client.get(
            _KRAKEN_OHLC_URL,
            params={"pair": canonical_to_kraken(instrument), "interval": spec.kraken_interval},
        )
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as exc:
        raise HistoryUnavailable(f"kraken request failed: {exc}") from exc
    if body.get("error"):
        raise HistoryUnavailable(f"kraken: {body['error']}")
    return parse_kraken_ohlc(body)


async def _fetch_alpaca(
    client: httpx.AsyncClient, instrument: str, spec: RangeSpec, settings: EquityFeedSettings
) -> list[Bar]:
    if not settings.api_key:
        raise HistoryUnavailable("equity history needs EQUITY_FEED_API_KEY")
    start = (datetime.now(UTC) - timedelta(days=spec.lookback_days)).date().isoformat()
    try:
        resp = await client.get(
            _ALPACA_BARS_URL.format(symbol=instrument),
            params={"timeframe": spec.alpaca_tf, "start": start, "feed": "iex", "limit": 10000},
            headers={
                "APCA-API-KEY-ID": settings.api_key,
                "APCA-API-SECRET-KEY": settings.api_secret,
            },
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HistoryUnavailable(f"alpaca request failed: {exc}") from exc
    return parse_alpaca_bars(resp.json())
