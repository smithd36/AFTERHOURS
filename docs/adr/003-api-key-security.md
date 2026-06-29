# ADR-003: API Key Security Policy

**Status:** Accepted - binding, non-negotiable
**Date:** 2026-06-09
**Deciders:** @smithd36

---

## Context

AFTERHOURS will eventually place orders with real money via exchange APIs. A compromised API key with withdrawal permissions would allow an attacker to drain the account. A compromised key with trade permissions could cause catastrophic losses. These risks require explicit, binding policy - not just convention.

---

## Decision

### Rule 1: Read-only, withdrawal-disabled keys only

**All API keys used in this system must be:**
- **Read-only** - no trading permissions for Phase 0–2 (data only)
- **Withdrawal-disabled** - this permission must be explicitly disabled on the exchange, not just absent from the key scope
- **Trade-enabled only when a specific phase requires it** - and only after the risk engine and kill switch are fully operational

Never create a key with withdrawal permissions for use with this system. If an exchange does not allow creating keys without withdrawal permissions, do not use that exchange.

### Rule 2: Never commit real keys

Real API keys never appear in:
- Any file tracked by git
- Commit messages
- Pull request descriptions
- Log output (the logging config must not log config values at DEBUG level)

`.env` is in `.gitignore`. `.env.example` contains only placeholders, never real values.

If a key is accidentally committed, it must be revoked immediately on the exchange - not just removed in a follow-up commit. Git history preserves the exposure.

### Rule 3: Keys live in `.env` only

The only accepted source for API keys is environment variables, loaded via pydantic-settings from `.env`. Hard-coded keys in source files are not permitted.

### Rule 4: Phase 0–3 require no keys

The Coinbase Advanced Trade public WebSocket endpoint does not require authentication for market data. Phases 0 through 3 are entirely public-data-only. No API key needs to be configured until Phase 4 (execution).

---

## Enforcement

| Mechanism | How it enforces the policy |
|---|---|
| `.gitignore` | Ignores `.env` and `.env.*` (except `.env.example`) |
| `.env.example` | Template contains only variable names and comments - no real values |
| `pydantic-settings` | Settings classes load from env vars; no defaults for key fields |
| Code review | Any PR adding a key string to source is blocked |

---

## Consequences

### Positive
- Worst-case blast radius from a key leak: attacker can read account balances and order history. Cannot trade. Cannot withdraw funds.
- Audit trail of when keys were introduced (git log on `.env.example`).
- Clear policy removes ambiguity - "I'll just put it here temporarily" is explicitly prohibited.

### Negative / constraints
- Slightly more setup friction - developers must configure `.env` manually before running.
- When Phase 4 introduces trading keys, the permissioning model must be revisited - those keys will need trade scope but must remain withdrawal-disabled.

---

## Exchange-Specific Notes

### Coinbase Advanced Trade
- Create keys at: Coinbase → Settings → API
- Required permissions for Phase 4: `View`, `Trade` on specific portfolios
- `Withdraw` must be unchecked - verify this explicitly after key creation
- Keys are scoped to portfolios, not the full account - create a dedicated portfolio for AFTERHOURS with limited funding

### Kraken (alternate)
- Create keys at: Kraken → Security → API
- Withdrawal permissions are a separate checkbox - verify it is off
- IP allowlisting is available and recommended

---

## Revision History

- **2026-06-09**: Initial policy. Read-only + withdrawal-disabled binding from day one.
