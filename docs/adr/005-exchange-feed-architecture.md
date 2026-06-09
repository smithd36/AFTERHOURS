# ADR-005: Exchange Feed Architecture — Kraken Primary, Coinbase Deferred

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** Lead Architect

---

## Context

Phase 1 requires a reliable live market data feed. Two exchanges were planned (PLANNING §3): Coinbase Advanced Trade as primary and Kraken as alternate.

During Phase 1 implementation, connecting to the Coinbase Advanced Trade WebSocket (`wss://advanced-trade-ws.coinbase.com/ws`) timed out at the opening handshake. Investigation confirmed that Coinbase now requires JWT authentication even for public ticker subscriptions — a policy change made in 2024 that was not in effect when the planning document was written.

Two paths were available:

1. **Implement Coinbase JWT auth now** — generate a read-only, withdrawal-disabled API key and wire in the authentication flow.
2. **Use Kraken as primary and defer Coinbase** — Kraken's WebSocket v2 (`wss://ws.kraken.com/v2`) provides equivalent public ticker data with zero authentication required.

---

## Decision

**Use Kraken WebSocket v2 as the primary market data feed. Defer Coinbase authentication to the execution phase.**

### Rationale

- **No auth means no key management risk in Phase 1–3.** Introducing real API keys before the risk engine and kill switch exist violates the layered safety model in ADR-003. Key management complexity should arrive at the same time as execution capability.
- **Kraken is a Tier-1 exchange** with a well-documented, stable WebSocket API. Data quality is equivalent for the instruments we track (BTC-USD, ETH-USD).
- **The Feed adapter pattern absorbs the swap cleanly.** Both `CoinbaseFeed` and `KrakenFeed` implement the same structural interface, publish identical `EventEnvelope(MARKET_TICK)` shapes with canonical instrument symbols, and are wired into the gateway lifespan identically. Switching back is a one-line change.
- **Coinbase remains fully implemented.** `ingestion/coinbase/` is complete and correct. It is simply not started in `default_lifespan` until auth is configured. The implementation is not lost — it is held in reserve.

### Canonical symbol normalisation

Both feeds emit payloads using the same canonical symbol format (`BTC-USD`, `ETH-USD`). Kraken's wire format uses `BTC/USD`; the `KrakenNormalizer` converts these transparently. Downstream consumers (price alert generator, frontend, future LLM layer) are exchange-agnostic.

```
Kraken wire: "BTC/USD" → KrakenNormalizer → payload.instrument = "BTC-USD"
Coinbase wire: "BTC-USD"  (already canonical)
```

### Kraken timestamp limitation

Kraken v2 ticker items carry no item-level timestamp. Both `event_time` and `ingest_time` are set to `datetime.now(UTC)` on receipt. This is a known deviation from the two-clock invariant (ADR-001): the venue clock is unavailable for Kraken ticks.

Consequence: price alert conditions and any downstream feature engineering that uses `event_time` for Kraken ticks are using our processing clock as a proxy, introducing potential millisecond-level inaccuracies. This is acceptable for Phase 1–3 (signal generation, thesis formation). For Phase 4+ (execution, backtesting), if Kraken remains primary, a microsecond-precision venue timestamp should be sourced from their REST trade history or level-2 feed.

---

## Consequences

### Positive
- Zero API key configuration required for Phases 1–3.
- Coinbase implementation preserved and ready — enabling it is a one-line gateway change.
- Normalised tick format means no downstream code changes when Coinbase is added.

### Negative / constraints
- Kraken ticks have no venue-side timestamp — `event_time == ingest_time`. Logged and accepted.
- When Coinbase is enabled alongside Kraken in a future phase, duplicate ticks for the same instrument will be published to the bus. Downstream consumers must tolerate or deduplicate them (by instrument + approximate time window).

---

## When to revisit

Enable `CoinbaseFeed` in `gateway/app.py` when:
1. Execution capability is being built (Phase 4), AND
2. A read-only, withdrawal-disabled Coinbase Advanced Trade API key has been created and added to `.env`.

See `docs/adr/003-api-key-security.md` for key requirements.
