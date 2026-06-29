# Phase 6A - Known Limitations

> Part of the AFTERHOURS documentation set ([`README.md`](README.md) for the index). Companion to
> [`adr/010-roadmap-rescope-alt-data-phase6.md`](adr/010-roadmap-rescope-alt-data-phase6.md).
> Phase 6A ships **three free** alternative-data feeds live (insider, lobbying+contracts,
> supply-chain) into the existing enrich-only pipeline. **Congress is built but deferred/dormant** -
> its only clean source (Quiver) went paid and the free JSON mirrors went dark (see Congress
> section). Dark-pool / options flow (paid) is also deferred.
>
> Each limitation below is **deliberate scope, not a bug** - recorded with its impact and the
> upgrade path so nothing is rediscovered the hard way. Format: *limitation → impact → upgrade.*

---

## Cross-cutting (pipeline integration)

- **Contextual signals rarely fire a thesis.** Lobbying and supply-chain signals are
  `direction: "neutral"` and are *not* thesis seeds. The thesis trigger uses a minutes-wide
  accumulation window, so a lone sparse signal ages out before another arrives.
  → *Impact:* these two feeds mostly land in the audit log; they only influence a thesis when they
  coincide with a seed or a burst on the same instrument.
  → *Upgrade:* a longer, per-signal-class in-buffer retention for sparse alt-data context (keep
  alt-data signals in the `ThesisGenerator` buffer for days, not minutes).

- **Enrich-only.** Alt-data drives theses only for instruments already on the watchlist (the risk
  engine needs a live price to size a stop).
  → *Impact:* a disclosure on an unwatched name is ingested and persisted but never traded.
  → *Partly addressed (Phase 6B.1, ADR-012):* the Discovery Engine now fuses unwatched-name
  disclosures by confluence into a ranked feed with **one-click watchlist-add** (manual). Still
  outstanding for **6B.2**: *auto*-add behind caps + a liquidity floor.

- ~~**No discovery UI surface yet.**~~ **Resolved (Phase 6B.1, ADR-012).** The terminal's **Discover
  workspace** surfaces unwatched-ticker alt-data as a ranked, AI-explained candidate feed
  (`/api/discovery`) with one-click watchlist-add, independent of the watchlist-filtered SignalFeed.

- **Only the `summary` reaches the LLM.** The thesis prompt renders `payload.summary`; structured
  fields (`direction`, `factor`, amounts) are not separately surfaced.
  → *Impact:* correlation/factor de-duplication (the `factor` tag) is advisory - it relies on the
  LLM reading the summary plus the calibration layer as backstop, not on numeric enforcement.
  → *Upgrade:* render `factor`/`direction` in the prompt and cap per-factor conviction (ADR-010
  §correlation).

- **No per-source reliability weighting.** Calibration is per-decision (and per-mode), not
  per-signal-source.
  → *Impact:* a noisy source isn't automatically down-weighted; the operator sees aggregate ECE.
  → *Upgrade:* attribute resolved outcomes back to contributing source types.

---

## Insider - SEC Form 4 (`ingestion/insider/`)

- **Rolling-window completeness.** Polls EDGAR `getcurrent` (count=100, every 5 min); during the
  post-close filing surge (≈4:00–5:30pm ET) Form 4s can scroll off between polls.
  → *Impact:* some filings are missed; this is not a completeness guarantee.
  → *Upgrade:* per-CIK polling of watched names, or a larger window / faster cadence near close.

- **Open-market codes only.** Materiality counts only non-derivative codes **P** (purchase) and
  **S** (sale); grants, option exercises, gifts, tax-withholding (A/M/G/F…) and all *derivative*
  transactions are dropped.
  → *Impact:* deliberate (those aren't discretionary informed trades), but option-heavy comp
  activity is invisible.

- **10b5-1 not distinguished.** A pre-planned 10b5-1 sale is treated identically to a discretionary
  open-market sale.
  → *Impact:* some "sells" carry less signal than they appear to.
  → *Upgrade:* parse the 10b5-1 flag and tag/down-weight planned sales.

- **One net direction per filing.** Mixed buys+sells in a single filing collapse to the
  dominant-side amount.
  → *Impact:* nuance lost on mixed filings.

- **Unvalued transactions skipped.** Transactions with missing/zero price-per-share can't be valued
  and are dropped.

- **Non-namespaced XML assumed.** A namespaced `ownershipDocument` variant would parse to nothing
  (returns `None` gracefully, no crash).

- **Unbounded transient retry.** A persistently failing filing `.txt` fetch is retried every poll
  until it scrolls off `getcurrent` (no backoff cap). Volume is tiny, so this is acceptable.

---

## Congress - Quiver (`ingestion/congress/`)

- **Deferred / dormant - no free source as of 2026-06-14.** Quiver removed its free API tier
  (cheapest now Hobbyist $30/mo, personal-use only), and the community free JSON mirrors
  (House/Senate Stock Watcher S3 buckets) are now `403 AccessDenied` - the project went dormant.
  The one still-live free source, the official House Clerk bulk
  (`disclosures-clerk.house.gov`), publishes only a filing-metadata XML index; the tickers/amounts
  live in per-filing **scanned/handwritten PDFs** (OCR territory) - a disproportionate, brittle
  build for the stalest signal in the set. The code is built against Quiver and wired into
  `default_lifespan`, but **no-ops cleanly without `QUIVER_API_TOKEN`**, so it costs nothing left
  dormant.
  → *Reactivate by:* either dropping in a paid `QUIVER_API_TOKEN` (the live-contract caveat below
  applies on first use), or, if a free JSON source reappears, swapping the normalizer/feed (the
  pipeline, seed-trigger, and dedup logic are source-agnostic).

- **Live contract unverified.** The auth scheme (`Authorization: Token …`), exact field names, and
  endpoint were built defensively but **not** verified against a live account.
  → *Impact:* first live use needs a smoke test; a 401/empty result points to the auth header or
  `QUIVER_BASE_URL` (both env-overridable, parsing is field-tolerant).

- **Inherent 30–45 day disclosure lag.** STOCK Act reporting is stale-by-design. `event_time` =
  `ReportDate` keeps it look-ahead-correct, but alpha freshness is capped.
  → *Impact:* signals must drive `swing`/`position` horizons, never `intraday`.

- **Composite dedup key.** Quiver has no per-row id; dedup is a hash of
  representative/ticker/date/transaction/range.
  → *Impact:* a later correction to any of those fields for the same trade could re-emit it.

- **Range lower-bound materiality.** Filings report dollar *buckets*; the smallest-bucket trades are
  dropped at the floor. Non-equity / optionable tickers are skipped.

---

## Government exposure - lobbying + contracts (`ingestion/govexposure/`)

- **Per-watched-equity only (no firehose).** Sources are name-keyed; the feed queries only watched
  equities.
  → *Impact:* contributes no Phase 6B discovery substrate (insider/congress are the discovery
  drivers).

- **Name-match fidelity.** Relies on each API's server-side search of the SEC-derived legal name.
  → *Impact:* subsidiaries lobbying/contracting under a different name are missed; common-word
  names can over-match and mis-attribute to the watched ticker.
  → *Upgrade:* alias lists / entity resolution.

- **Ticker→name map cached for process lifetime.** Loaded once from SEC `company_tickers.json`; a
  transient SEC failure makes the feed inert *that cycle* (it retries next poll), but a successfully
  loaded map is never refreshed.
  → *Impact:* a newly listed ticker added after startup won't resolve until a restart.
  → *Upgrade:* periodic map refresh.

- **Lobbying is non-directional.** `direction: "neutral"`, not a seed (see cross-cutting).

- **Contract modifications not handled.** Award amount is used as reported; de-obligations,
  amendments, and IDV modifications aren't netted.
  → *Impact:* an award and its later modifications can emit as separate signals.

- **USASpending publication lag.** `Action Date` is the award action, but USASpending itself lags by
  days–weeks; the lookback window (default 30d) also bounds cold-start volume and can miss
  older-but-recent items.

---

## Supply chain - 10-K customer concentration (`ingestion/supplychain/`)

- **Coarse regex, not NLP.** Extracts a sentence containing *customer + revenue keyword +
  percentage ≥ threshold*.
  → *Impact:* high false-negative rate (misses tables, non-standard phrasings) and possible false
  positives (any sentence matching the pattern). Public-filing proxy, deliberately simple
  (ADR-010).
  → *Upgrade:* structured XBRL / a paid relationship graph (FactSet/Bloomberg SPLC).

- **One dependency per 10-K.** Only the single highest-percentage sentence is emitted.
  → *Impact:* multiple distinct customer dependencies collapse to one signal.

- **Counterparty not linked.** The signal reports the dependency magnitude + raw sentence, not the
  named customer as an instrument.
  → *Impact:* can't yet propagate "customer Y in trouble → affects watched X."
  → *Upgrade:* named-entity extraction → counterparty ticker resolution.

- **Latest annual 10-K only.** 10-K/A amendments and 10-Q updates are ignored; the disclosure can be
  up to a year stale (annual cadence, weekly poll, 400-day lookback).

- **3 MB scan cap.** Very large filings are scanned only up to 3 MB; content beyond is ignored.

- **Shares the gov-exposure CIK/map limitations** (process-lifetime cache, SEC-fetch-inert cycle).

- **Non-directional / non-seed** (see cross-cutting).

---

## Legal / compliance

*Not legal advice. This records the compliance posture of the 6A feeds for the project's intended
use; revisit with counsel if scope changes (see the last subsection). Extends PLANNING §6.5.*

**Why 6A is clear for single-operator, own-capital use.** Every free feed consumes
**public-record, post-disclosure** data, so there is no material-non-public-information (MNPI) or
insider-trading exposure - the system acts on information that is already public when it arrives:

| Feed | Source | Status |
|---|---|---|
| Insider (Form 4) | SEC EDGAR | Public record |
| Congress | Quiver (repackaged STOCK Act filings) | Underlying data public record; vendor ToS applies (below) |
| Lobbying | Senate LDA | US government open data |
| Gov contracts | USASpending | US government open data |
| Supply chain | SEC 10-K filings | Public record |

Acting on these as a private trader is legal precisely *because* the data is published - there is no
"front-running Congress" offense for trading the public STOCK Act feed.

**The MNPI line is enforced in code.** Supply-chain is restricted to public 10-K filings only;
expert-network / channel-check sourcing is deliberately excluded (ADR-010, `SupplyChainSettings`
docstring). That is the one place this class of project typically strays into insider-trading
territory, and 6A stays out of it by construction.

**Regulatory posture (PLANNING §6.5).** Staying single-operator / own-capital - not managing others'
money, not publishing signals as advice, not taking custody - is what keeps the project out of
advisor/broker/MSB territory. The event-store audit log doubles as compliance evidence.

**Watch-items (the only two):**
1. **Quiver Terms of Service** - the one commercial source, and **now paid** ($30/mo Hobbyist, no
   commercial-use rights - personal consumption into a private terminal is within license). Only
   relevant if congress is reactivated on a paid token. Even then, **do not redistribute** Quiver's
   data - if terminal output is shown to others or republished, the vendor license applies. The
   three live feeds carry no such restriction. (Same redistribution principle PLANNING §6.5 raises
   for market data.)
2. **SEC fair-access User-Agent** - policy compliance, not legal risk. EDGAR requires a descriptive
   User-Agent with contact info; the `*_USER_AGENT` settings default to placeholders that 403 and
   must be set before live use. Polling stays well within SEC's 10 req/s limit.

**Where it would stop being clear** (out of 6A scope; get counsel before any of these): managing
others' capital, publishing or selling the signals as advice, redistributing vendor data, or
sourcing supply-chain intel from expert networks / channel checks.
