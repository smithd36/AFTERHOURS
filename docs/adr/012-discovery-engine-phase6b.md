# ADR-012: Discovery Engine - Phase 6B (Multi-Source Opportunity Surfacing)

**Status:** Accepted - **6B.1 implemented 2026-06-16** (`discovery/`, `/api/discovery`, Discover workspace, AI analyst); 6B.2 (breadth scanner / crypto-primary / auto-add + liquidity) pending
**Date:** 2026-06-16 (amended same day: MVP scoring execution model set to **pull-first** - see *Scoring execution model* and *Sequencing*)
**Deciders:** Operator, @smithd36

---

## Context

ADR-010 inserted alternative-data ingestion as Phase 6 and reserved **Phase 6B -
auto-discovery** as a one-line placeholder: "promote a high-conviction alt-data signal on an
unwatched instrument to auto-add it to the watchlist, behind caps + liquidity-aware sizing."
That framing is too narrow on two counts:

1. **Single-source, alt-data-only.** It promotes off *one* material disclosure. The actual goal is
   to surface assets worth investigating *earlier than standard tools* - which comes from the
   **confluence of many weak signals**, not any single one, and should draw on **all** available
   data, not just the 6A alt-data feeds.
2. **Equity-only.** Alt-data (Form 4, lobbying, 10-K) has no crypto analogue. A discovery system
   that ignores crypto leaves the existing crypto book undiscoverable.

This ADR expands 6B from "auto-add on a strong disclosure" into a **Discovery Engine**: a
control-plane layer that fuses weak signals across domains into a small, ranked, explained set of
candidates. Equity-primary, crypto-secondary. It is explicitly a *control-plane* concern (admission
to the watchlist), not new ingestion - the bus contract is the plug, exactly as in 6A.

---

## Decision

**A new top-level `discovery/` package owns multi-source candidate surfacing.** It depends on
`core/` only, reads signals from the persisted event store, and promotes candidates through the
existing `WatchlistManager.add(...)` path. The LLM sits *on top of* scored candidates, never on the
firehose.

### Pipeline

```
sources → SignalExtractors → EntityResolver → ConvictionAccumulator → DiscoveryEngine
                                                                            │
                                                          ranked candidates (/api/discovery)
                                                                            │
                                                    AIAnalyst (top-K) → discovery.analysis
                                                                            │
                                                       Discover workspace → watchlist add
```

The pipeline stages are the same regardless of *when* scoring runs; the next section settles that.

### The source split that drives the design

Data sources divide by **how they name an unwatched instrument**, and only one class is free:

- **Disclosure-driven** (alt-data, news/RSS) already *mention* unwatched tickers; 6A persists them
  today. Extractors subscribe to `signal.created` and normalize. **Zero new ingestion.**
- **Market-data-driven** (volume/volatility anomalies, new listings) is **watchlist-scoped** today
   - `market.tick` never carries an unwatched name. Surfacing these needs a **broad universe
  scanner** polling *outside* the watchlist. This is the only genuinely new ingestion 6B adds, and
  it is deferred to 6B.2.

### Scoring execution model - pull-first

*When* scoring runs (not how) is the load-bearing architectural choice. It is a push-vs-pull axis:

| | A - Streaming (push) | B - Batch (pull, timer) | C - On-demand (pull, lazy) |
|---|---|---|---|
| Scoring trigger | every `signal.created` | interval recompute over a window | when the panel is opened |
| Latency to candidate | seconds | minutes | on open |
| Proactive alerts | native (emits event) | snapshot diff | none |
| State to rehydrate on restart | **yes** (stateful subscriber) | none | none |
| Re-score with new weights | hard (replay/migrate) | trivial (re-run) | trivial |
| Existing pattern reused | bus subscriber | new job | **ADR-011 equity-curve projection** |
| Complexity | highest | medium | lowest |

**Decision: C (on-demand projection) for the 6B.1 MVP, structured to grow into B, and only A if
proactive alerting is later shown to be needed.** Discovery is an inherently slow-horizon problem -
disclosures are ≤2-day-old and stay material for weeks - so paying streaming's stateful-rehydration
complexity to shave minutes off a multi-day signal is a poor trade for v1. The score is computed as
a **read-side projection over the persisted `signal.created` events**, exactly as `analytics/`
builds the equity curve on demand (ADR-011): no stateful subscriber, no new write path,
replay-reproducible. Batch is then "run the same projection on a timer"; streaming is "move it into
a subscriber" - both are evolutions of the identical scoring core, not rewrites.

### Modules (`discovery/`)

- **`SignalExtractor`** (per source) - persisted `signal.created` event / scan poll → normalized
  `DiscoveryContribution{instrument_ref, factor, value∈[0,1], half_life, summary}`. Each extractor
  knows its own units; the engine only ever sees bounded, tagged contributions. Pure mapping - no
  state of its own.
- **`EntityResolver`** - source-specific ref (ticker / SEC CIK / company name / crypto symbol /
  contract address) → a **canonical instrument key**. **Drops on ambiguity** - never guesses an
  asset it would trade.
- **`ConvictionAccumulator`** - the scoring core: a **pure function** that folds the resolved
  contribution window into per-instrument `{score, contributions[]}` (decay-by-age, confluence
  merge - below). No persisted state; the event store *is* the state. (When evolved to push/batch
  it becomes incremental, but the merge math is unchanged.)
- **`DiscoveryEngine`** - orchestrates extract → resolve → score → rank as an **on-demand projection
  over the event store** serving `/api/discovery`; owns the control plane (cap, TTL, cooldown) at
  promotion time.
- **`MarketScanner`** *(6B.2)* - broad-universe poller: Alpaca screener (most-actives/movers),
  CoinGecko `/coins/markets` by volume, Kraken `AssetPairs` for new listings.
- **`AIAnalyst`** - LLM pass over top-K candidates → `discovery.analysis`. Reuses the existing
  provider layer (`create_provider`, `ThrottledProvider`, response cache, `prompt_hash`).

### Scoring - confluence, not sum

A per-instrument conviction accumulator. This is the heart of "weak signals → strong opportunity."

- **Normalize.** Every extractor maps raw output to a bounded contribution `∈[0,1]` (alt-data
  reuses 6A materiality; anomalies use a squashed z-score vs rolling baseline; news uses
  recency × source-tier × count). The engine never sees raw units.
- **Weight.** `static_source_weight × extractor_confidence`. Equity sources weighted above crypto
  for the equity-primary stance. **Weights are config (pydantic settings), not code** - they are
  priors, not optimized values (see Open question 1).
- **Time-decay.** Exponential, **per-source half-life** (a volume spike decays in hours; an insider
  buy stays material for weeks). Decay-on-read - no background sweep, no wall-clock timer (consistent
  with ADR-011's event-time discipline).
- **Merge = confluence.** Two stages: (1) group by `factor`, saturate within a factor so five news
  articles ≈ one news factor (the 6A factor tags exist for exactly this); (2) combine across factors
  with **noisy-OR** (`1 − Π(1 − cᵢ)`) plus a small **confluence bonus** when ≥2 distinct factor
  *families* fire - so two independent factors beat one loud signal.
- **Negative evidence subtracts** (insider *selling*, dilution, downgrades) - or the score is a hype
  meter, not a conviction score.

**Explainability is a property of the model, not a bolt-on.** Because the score is a transparent
combination of tagged, weighted, decayed, named contributions, the `contributions[]` list *is* the
explanation - it feeds both the UI breakdown and the AIAnalyst prompt. **No ML ranker for MVP**;
revisit once `calibration/` has produced outcome labels to learn weights from.

### AI analyst layer

The LLM runs **only on candidates above θ** (bounded cost, pre-curated evidence). It produces
structured output - why interesting, **risks & counter-signals** (explicitly prompted for the bear
case, to fight the additive accumulator's upward bias), an evidence summary, a suggested next step.
**It does not decide or size** - same invariant as the Decision object: the LLM provides reasoning,
never the action. Promotion stays deterministic (threshold + caps). It is a *cousin* of
`ThesisGenerator` (which builds trading theses on *watched* names), not the same component.

### Control plane (shared across both markets)

- **Cap with provenance** - separate budget for `source="discovery"` watchlist entries so discovery
  cannot crowd out operator-curated names. Bounded growth is the exit criterion.
- **Auto-add + TTL expiry** (Paper) / **operator confirm** (higher autonomy). The confirm path is
  the existing one-click watchlist-add UI; 6B pre-stages a candidate into it.
- **Cooldown / hysteresis** - don't re-discover a just-expired name.
- **Liquidity** - admission floor at discovery (reject a microcap you couldn't exit) + an ADV-%
  size cap in the risk engine (which is liquidity-blind today).

### Events & surfaces

- The **ranked candidate feed is served by the `/api/discovery` projection**, not streamed - so
  `discovery.candidate` is *not* a bus event in the pull-first MVP (it becomes one only if/when the
  push model is adopted). The events that *are* real state changes / audit records stay on the bus:
  `discovery.promoted`, `discovery.expired` (control-plane actions on the watchlist) and
  `discovery.analysis` (the LLM output) - new `EventType` members mirrored in
  `frontend/src/types/core.ts`.
- New route `/api/discovery` (ranked feed) + a `useDiscovery` reducer feeding a **Discover
  workspace** - not a standalone panel. The terminal is reorganized from a flat panel set into three
  workflow workspaces, **Discover · Terminal · Review** (generalizing the existing desktop
  `ViewSwitcher`, and segmenting the mobile tab bar by workspace so it stays ≤4 tabs instead of one
  7-tab bar). Discover is the *pre-watchlist funnel* and absorbs watchlist management; Terminal is
  the live pipeline; Review is outcomes.
  - **Discover workspace** holds the ranked candidate list (symbol · opportunity score · score
    sparkline · factor chips · age · market filter; expand → evidence detail + AI analysis with
    counter-signals shown at equal weight + one-click add / dismiss) alongside the watchlist table.
    The full watchlist-management UI is extracted into a shared component reused by both this
    workspace and the existing quick-edit `W` drawer (retained for curation from any workspace).
    Surfaces uncertainty honestly (PLANNING §6.6 anti-complacency) - it reads as triage, not a buy.
  - The global pending-approval indicator moves onto the workspace switcher so a Decisions approval
    still pulls the operator back from Discover/Review (preserving the act-surface-never-hidden rule).

### Frontend sequencing - workspace shell ships first

The workspace reorganization has **no backend dependency** and is the first deliverable. PR 1 lands
the Discover/Terminal/Review shell, the shared watchlist component, and a Discover workspace
containing watchlist management + a "Discovery candidates - Phase 6B" empty state - so the
navigation improvement (and the mobile tab reduction) ships independently of, and ahead of, the
`discovery/` backend. The 6B.1 backend (below) then fills the empty state via `useDiscovery`; no
further navigation changes.

---

## Consequences

### Positive
- Discovery becomes multi-source confluence, matching the actual product goal, while reusing the
  bus, event store, 6A materiality/factor tags, `WatchlistManager.add`, the LLM layer, and the
  one-click-add UI - almost no greenfield ingestion in the MVP.
- The scoring model is deterministic and inspectable; explanation falls out of the score structure.
- Equity (disclosure-driven) discovery ships without waiting on the scanner; crypto-primary
  (scan-driven) slots into the *same* engine later rather than a parallel system.

### Negative / constraints
- **Entity resolution is the dominant risk** - a wrong resolution puts conviction on the wrong
  asset. Mitigated by drop-on-ambiguous, but company-name→ticker (lobbying/contracts) stays hard.
- A discovery system surfaces *more* candidates earlier - by construction it trades precision for
  recall, so alert-fatigue management (threshold, cooldown, cap) is load-bearing, not optional.
- Source weights are unfalsifiable until outcomes accumulate; the MVP ships priors, not tuned values.

---

## Alternatives considered

**Keep the ADR-010 single-disclosure auto-add.** Rejected: promotes off one signal, ignores
confluence and crypto - it is a feature, not the discovery system the product needs.

**Per-source discovery rules (one promoter per feed).** Rejected: no cross-source confluence, N
copies of the cap/TTL/liquidity logic, and double-counting of correlated sources.

**An ML ranking model from day one.** Rejected: no labeled outcomes yet, and it destroys
explainability. The deterministic accumulator is explainable and good enough; ML re-ranking is a
later phase once `calibration/` supplies labels.

**A streaming stateful accumulator for the MVP (push).** Considered and deferred (see *Scoring
execution model*). Its only real advantage is sub-minute alerting, which a multi-day-horizon signal
does not need; against that it adds a stateful subscriber to rehydrate on restart and bakes the
scoring formula into live state, making weight iteration expensive. Pull-first gets the same scoring
math with none of that, and the push model remains a clean later evolution.

**Fold discovery into `WatchlistManager` or the feeds.** Rejected: the manager is a registry, the
feeds are ingestion; discovery is scoring *policy* and belongs in its own module (mirrors how
`RiskEngine` is a separate deterministic gate).

---

## Open questions

1. **Weight calibration.** Ship config priors now; later, re-weight sources by their realized hit
   rate using `calibration/` outcome labels. Until then weights are operator-tuned, not learned.
2. **MVP scanner scope.** 6B.1 (disclosure-driven, equity-primary) ships without the scanner;
   6B.2 adds it for crypto-primary. Confirm this split holds at 6B.1 exit rather than pulling the
   scanner forward.
3. **Auto-add vs. confirm default.** Start fully manual (candidate feed + one-click add); enable
   auto-add + TTL only after the candidate quality is observed in Paper.

---

## Relationship to other ADRs

- **Supersedes the Phase 6B definition in ADR-010** (auto-discovery placeholder) with this expanded
  Discovery Engine. ADR-010's renumber (live trading → Phase 7) is unchanged.
- **ADR-001 (event bus):** discovery is a read-side projection over the persisted event store plus a
  few new control-plane/audit event types; no change to existing producers.
- **ADR-011 (analytics):** the scoring projection directly reuses ADR-011's on-demand,
  event-time-keyed, no-wall-clock-timer pattern (as the equity curve does); the ADV-% liquidity cap
  is a risk-engine sizing input, distinct from analytics' retrospective metrics.

---

## Sequencing

1. **PR 1 - workspace shell (frontend only, no backend dependency).** Generalize `ViewSwitcher` to
   **Discover · Terminal · Review** and segment the mobile tab bar by workspace; extract the shared
   watchlist-management component (reused by the Discover workspace and the `W` drawer); Discover
   workspace = watchlist management + a "Discovery candidates - Phase 6B" empty state; move the
   pending-approval indicator onto the workspace switcher. Ships the nav/mobile improvement ahead of
   any backend.
2. **6B.1 - disclosure-driven discovery (equity-primary), pull-first.** `discovery/` package,
   extractors over the persisted `signal.created` events, entity resolver (clean keys,
   drop-on-ambiguous), conviction accumulator as an **on-demand projection** served by
   `/api/discovery`, a `useDiscovery` reducer filling the Discover workspace candidate feed, AIAnalyst
   on top-K, liquidity admission floor, **manual** promotion via the existing one-click add. No new
   external feeds, no stateful subscriber.
3. **6B.2 - breadth scanner (unlocks crypto-primary).** `MarketScanner` (Alpaca screener, CoinGecko
   volume, Kraken listings) feeding the same projection; if alerting latency matters, move scoring to
   batch (timer) or push (subscriber) here - same scoring core; auto-add + TTL + cooldown; ADV-% size
   cap in the risk engine.
