# AFTERHOURS — Architecture & Product Planning Document

> **Status:** Draft v0.1 — pre-implementation
> **Author:** Lead Architect
> **Date:** 2026-06-09
> **Audience:** Founder, engineering, future contributors

This document defines the vision, architecture, risks, workflows, and roadmap for AFTERHOURS **before any code is written**. It is intentionally opinionated. Where I challenge the brief, I say so explicitly.

---

## 0. Executive Summary

AFTERHOURS is an **AI-assisted trading terminal**: a decision-support and execution platform that ingests market data and news, reasons over it with LLMs and quantitative models, generates trade hypotheses with explicit confidence and risk, and — under operator-controlled autonomy — executes them across crypto and equity accounts. It presents all of this through a real-time, terminal-inspired web dashboard.

The single most important design principle: **AFTERHOURS is a human-in-the-loop system by default, with graduated autonomy as a configurable privilege, not a starting assumption.** The LLM is a *hypothesis generator and analyst*, never an unsupervised fund manager. Every dollar of real risk passes through a deterministic risk engine and an audit trail.

The second principle: **the reasoning is the product.** Anyone can wire an LLM to a broker API. The defensible, valuable, and *safe* thing is surfacing *why* a decision was made — confidence, evidence, risk, historical analogues — so the operator can trust, correct, and improve it.

---

## 1. Product Vision

### 1.1 What it is
A futuristic trading terminal where an operator sits in front of live feeds — news, prices, the AI's evolving "thoughts," portfolio state — and collaborates with an AI co-pilot that never sleeps. The AI watches markets around the clock (hence *AFTERHOURS*), forms theses, flags opportunities and threats, and proposes actions. The operator approves, rejects, tunes, or delegates.

### 1.2 What it is *not* (scope discipline)
- **Not** a fully autonomous black-box money printer. That framing is how people lose accounts and attract regulators.
- **Not** a high-frequency / latency-arbitrage system. LLM reasoning operates on seconds-to-minutes timescales, not microseconds. We deliberately play in the **discretionary / swing / event-driven** timeframe where reasoning adds value and latency is forgiving.
- **Not** financial advice for third parties (at least initially). Single-operator tool. This materially changes the regulatory surface — see §6.

### 1.3 Target operator
A technically literate trader/quant/builder who wants leverage from AI but insists on understanding and controlling what it does. They value transparency over magic.

### 1.4 The "feel"
Bloomberg Terminal × a sci-fi ops console × a pair-programming copilot. Dense, fast, keyboard-driven, dark, monospaced, information-rich. Latency-aware UI (every panel shows its data freshness). The operator should feel like a mission commander, not a slot-machine player.

### 1.5 North-star metric
Not "return %." Early on, returns are noise and a dangerous thing to optimize toward. The north star is **calibration + auditability**: does the system's stated confidence match realized outcomes, and can every action be explained and reconstructed? A system you can trust compounds; a lucky one blows up.

---

## 2. Major Subsystems

I group the platform into eleven subsystems. They map cleanly onto modules and, later, services.

```
                          ┌──────────────────────────────────────────────┐
                          │            OPERATOR (Terminal UI)             │
                          │   feeds · decision queue · portfolio · audit  │
                          └───────────────▲───────────────┬──────────────┘
                                          │ WS/SSE        │ commands (REST)
                          ┌───────────────┴───────────────▼──────────────┐
                          │              API / Gateway Layer              │
                          └───────────────▲───────────────┬──────────────┘
                                          │               │
                 ┌────────────────────────┴───────────────┴─────────────────────────┐
                 │                       EVENT BUS / MESSAGE SPINE                    │
                 └─┬─────────┬──────────┬──────────┬──────────┬──────────┬───────────┘
                   │         │          │          │          │          │
        ┌──────────▼─┐ ┌─────▼─────┐ ┌──▼───────┐ ┌▼────────┐ ┌▼────────┐ ┌▼─────────┐
        │ Ingestion  │ │  Signal/  │ │ Reasoning│ │  Risk   │ │Execution│ │Portfolio │
        │ (mkt/news) │ │ Feature   │ │  Engine  │ │ Engine  │ │ Engine  │ │ & Ledger │
        │            │ │  Store    │ │  (AI)    │ │(gatekpr)│ │(brokers)│ │          │
        └──────────┬─┘ └─────┬─────┘ └──┬───────┘ └─┬───────┘ └─┬───────┘ └─┬────────┘
                   │         │          │           │           │           │
                 ┌─▼─────────▼──────────▼───────────▼───────────▼───────────▼─┐
                 │       PERSISTENCE · AUDIT LOG · OBSERVABILITY · SECRETS     │
                 │   (timeseries · relational · object · vector · metrics)    │
                 └────────────────────────────────────────────────────────────┘
                                    Backtest/Sim Engine replays
                                    the same path with mock adapters
```

### 2.1 Data Ingestion Layer
Pulls and normalizes external reality into internal events.
- **Market data:** quotes, OHLCV, order book depth, funding rates. Crypto (exchange WS/REST) and equities (broker/market-data vendor).
- **News & text:** financial news APIs, RSS, filings (SEC EDGAR), economic calendars, optionally social (X/Reddit) with heavy skepticism.
- **Alt/structured signals:** on-chain metrics, options flow, volatility surfaces, sentiment indices.
- Normalizes everything to a canonical schema, timestamps with source + ingest time, deduplicates, and publishes to the bus. **Provenance is mandatory** — every datum carries where it came from and when.

### 2.2 Signal / Feature Store
Turns raw events into features the reasoning and risk layers consume.
- Technical indicators, rolling stats, regime labels, news-to-instrument linking + relevance scoring, embeddings for semantic search over historical context.
- Serves both **online** (live features for live decisions) and **offline** (point-in-time-correct features for backtests). **Avoiding look-ahead bias is a first-class requirement**, not an afterthought.

### 2.3 Reasoning Engine (the AI core)
Generates hypotheses, analyses, and proposed actions.
- Orchestrates LLM calls with retrieved context (RAG over news, historical analogues, current positions).
- Produces a structured **Decision Object** (see §3.4): thesis, supporting/contradicting evidence, confidence, suggested instrument/size/direction, time horizon, invalidation conditions, and risk notes.
- Combines LLM judgment with deterministic quantitative models (don't let the LLM invent numbers it should compute). LLM for *narrative, synthesis, and event interpretation*; code for *math, sizing, and statistics*.

### 2.4 Risk Engine (the gatekeeper)
**Deterministic, non-AI, and authoritative.** Every proposed action passes through it. The LLM cannot bypass it.
- Position limits, per-trade and portfolio max loss, exposure caps per asset/sector/correlation cluster, leverage limits, drawdown circuit breakers, kill switch.
- Pre-trade checks (can we afford it, does it violate limits) and continuous post-trade monitoring (stop-losses, margin, exposure drift).
- Owns the **emergency halt**: one button/command flattens or freezes everything.

### 2.5 Execution Engine
Translates approved decisions into broker/exchange orders.
- Adapter pattern: one interface, pluggable backends (paper, crypto exchanges, equity brokers).
- Smart order handling: order types, partial fills, retries, idempotency (critical — never double-submit an order), slippage tracking, reconciliation against broker state.
- Emits fills back onto the bus for the ledger and UI.

### 2.6 Portfolio & Ledger
The source of truth for what we own and how we're doing.
- Positions, cash, P&L (realized/unrealized), performance attribution, trade history.
- Reconciles continuously against broker/exchange reported state — **never trust internal state alone; the broker is ground truth for balances.**

### 2.7 Backtesting / Simulation Engine
Replays historical (or live-shadow) data through the *same* reasoning/risk/execution path with mock adapters.
- Paper trading mode is just the execution adapter swapped for a simulated fill model.
- Supports strategy experimentation, A/B of prompts/models, and **calibration measurement** (predicted vs realized).

### 2.8 Orchestration / Event Bus
The spine. Decouples subsystems, enables replay, and is the backbone of auditability.
- Every meaningful thing is an immutable event. The audit log *is* the event stream.

### 2.9 Persistence Layer
Polyglot by necessity (see §4.4): time-series for prices, relational for orders/positions/audit, object store for raw payloads, vector store for semantic retrieval.

### 2.10 Observability & Audit
Logs, metrics, traces, plus a **domain-specific audit trail**: every decision, the inputs it saw, the model/prompt version, the risk verdict, the execution result. Must be able to answer "why did we buy X at 14:32?" months later, deterministically.

### 2.11 Identity, Secrets & Access
API keys = direct access to money. Encrypted secret storage, least privilege, scoped/withdrawal-disabled exchange keys, MFA on the operator console, full action attribution.

---

## 3. Core Domain Concepts (the data model that everything orbits)

Getting these right matters more than any framework choice.

### 3.1 Instrument
Canonical identity for a tradable thing across venues (e.g., `BTC-USD` on three exchanges is one logical instrument with venue-specific mappings). Avoids the classic bug of treating the same asset on two venues as unrelated.

### 3.2 Signal
A normalized observation: `{source, type, instrument(s), timestamp, payload, provenance, confidence}`. News items, indicator crossings, on-chain spikes all become Signals.

### 3.3 Thesis
A longer-lived belief the system holds ("BTC re-rating on ETF inflows; valid while inflows > X and price > Y"). Theses persist across many decisions, have invalidation conditions, and are revisited. This is what makes the system feel like it *thinks* rather than reacting tick-by-tick.

### 3.4 Decision Object
The central artifact. Immutable once created. Roughly:
```
Decision {
  id, created_at, originating_thesis_id?,
  inputs: [signal_ids...],            // exactly what it saw (point-in-time)
  model: {provider, name, version, prompt_hash, temperature},
  proposal: {instrument, side, size, order_type, time_horizon},
  reasoning: {thesis_text, supporting[], contradicting[]},
  confidence: 0..1,                   // and calibration bucket
  risk: {max_loss, stop, invalidation_conditions[], risk_engine_verdict},
  status: proposed|approved|rejected|expired|executed|failed,
  human: {actor, action, note, ts}?,  // operator interaction
  outcome: {fills[], realized_pnl, closed_at}?  // filled in later
}
```
Everything else hangs off this. The audit trail is the lifecycle of Decision Objects.

### 3.5 Order / Fill / Position
Standard execution primitives, but with strict idempotency keys and reconciliation status.

---

## 4. Architecture Options & Recommendations

### 4.1 Decomposition: monolith vs microservices vs modular monolith
| Option | Pros | Cons |
|---|---|---|
| Single script / monolith | Fast to start, easy to reason | Becomes unmaintainable; can't scale ingestion independently; one crash kills trading |
| Full microservices | Independent scaling, fault isolation | Massive ops overhead for a 1-operator product; premature |
| **Modular monolith + event bus (RECOMMENDED)** | Clean module boundaries, single deploy, but ready to split | Requires discipline to keep boundaries clean |

**Recommendation:** Start as a **modular monolith** organized along the §2 subsystem boundaries, communicating through an in-process (later out-of-process) **event bus**. Each module exposes a narrow interface and never reaches into another's internals. When a module needs independent scaling or isolation (ingestion and execution are the first candidates), extract it to a service *without* changing its contract. This buys microservice-grade boundaries at monolith ops cost.

### 4.2 Event-driven core
Make the event bus central from day one. Benefits compound: live UI feeds are just bus subscriptions; the audit log is the event stream; backtesting is replaying the stream; adding a new consumer (e.g., a new risk monitor) doesn't touch producers. **This is the single highest-leverage architectural decision.**

- Start: lightweight in-process pub/sub + durable append-only event store (Postgres table or NATS/Redis Streams).
- Scale: Kafka/NATS JetStream/Redis Streams when throughput demands.

### 4.3 Language & stack recommendation
- **Backend / trading core: Python.** The entire quant + LLM ecosystem lives here (pandas, numpy, vectorbt, ccxt, broker SDKs, the AI SDKs). For our timescale, Python's latency is a non-issue. Use `asyncio` for concurrent feeds.
  - *Where Python hurts* (hot numeric loops in backtests): drop to vectorized numpy or a Rust/C extension surgically. Don't rewrite the platform in Go/Rust for latency we don't need.
- **Frontend: TypeScript + React + Vite.** Component foundation: **Tailwind CSS v4** (utility-first, dark-mode-first) + **shadcn/ui** (accessible Radix-based components, fully owned in-repo). For the terminal aesthetic: `xterm.js` for genuine terminal panes; `lightweight-charts` (TradingView) for price; a virtualized feed list for high-volume streams. shadcn's design system gives a consistent, composable base without locking into a third-party library — components live in `frontend/src/components/ui/` and are fully forkable.
- **Transport:** WebSockets (or SSE) for server→UI streaming; REST/RPC for commands.
- **Contracts:** Define event/Decision schemas once (Pydantic on the backend, generated TS types on the frontend) so the wire format can't drift.

*Alternative considered:* a single TS/Node full-stack. Rejected — cedes the Python quant/AI ecosystem, which is the core of the product. Polyglot (Python core + TS UI) is worth the seam.

### 4.4 Storage choices
| Need | Choice | Why |
|---|---|---|
| Orders, positions, audit, Decision Objects | **PostgreSQL** | ACID, the system of record; trades and audit must be transactionally correct |
| Time-series prices/metrics | **TimescaleDB** (Postgres extension) or ClickHouse | Cheap to run alongside Postgres early; ClickHouse if volume explodes |
| Raw payloads (news bodies, snapshots) | Object store (S3/MinIO) | Cheap, immutable, keeps Postgres lean |
| Semantic retrieval over news/history | **pgvector** (in Postgres) early, dedicated vector DB later | One fewer system to run at first |
| Hot state / pub-sub / cache | **Redis** | Live quotes, rate limiting, ephemeral state |

**Recommendation:** Lean on Postgres for as much as possible early (Timescale + pgvector are extensions). Fewer moving parts = fewer ways to lose data or money. Add specialized stores only when a real bottleneck appears.

### 4.5 LLM / reasoning architecture
- **Provider-abstracted.** Never hardcode one model vendor. Wrap behind an interface; record model+version+prompt hash on every Decision (for audit + A/B + calibration).
- **Structured output, always.** Decisions come back as validated JSON (tool/function calling or structured outputs), never free text the parser guesses at.
- **RAG for context:** retrieve relevant recent news, the current portfolio, open theses, and *historical analogues* ("last 5 times CPI surprised hot, here's what happened"). The historical-analogue retrieval is a differentiator.
- **Separation of duties:** LLM proposes *narrative + direction*; deterministic code computes *sizing, risk numbers, and statistics*. Never let the model free-hand position sizes.
- **Guardrails:** every LLM output is schema-validated, range-checked, and then must still clear the deterministic risk engine. Treat the LLM as a *brilliant but unaccountable intern*: great ideas, zero signing authority.
- **Cost/latency control:** cache, batch, use cheaper models for triage and stronger models for committed analysis (a tiered cascade).

### 4.6 Time, the silent killer
Two clocks: **event time** (when it happened in the market) and **ingest/processing time** (when we saw it). The feature store and backtester must use event time with point-in-time correctness. Most backtest-to-live failures are subtle look-ahead bugs. Architect for this now; retrofitting is brutal.

---

## 5. Modes of Operation

A spectrum of autonomy, explicitly configurable and per-scope (you can run crypto autonomous while equities stays manual):

1. **Observe (read-only).** No orders. AI watches, narrates, generates theses and would-be decisions. The default for a new account and for evaluating a new strategy/model. Logs "shadow decisions" for calibration without risk.
2. **Paper / Simulation.** Full pipeline, simulated fills, virtual balance. For strategy dev and trust-building.
3. **Assisted (manual approval).** AI proposes; **every** order requires explicit operator approval in the Decision Queue. The default live mode.
4. **Semi-autonomous (bounded).** AI executes within a tight, pre-approved envelope (instrument whitelist, max size, max trades/day, max daily loss); anything outside the envelope escalates to manual. Operator can revoke instantly.
5. **Autonomous (supervised).** AI executes within broader limits; operator monitors and can halt. **Only earned after a model demonstrates calibration over a meaningful sample in paper + assisted modes.** Never the default. Always under the risk engine and kill switch.

Mode transitions are themselves audited events. There is always a **global kill switch** that flattens/halts regardless of mode.

---

## 6. Risks & Constraints (the part that matters most)

### 6.1 Financial
- **Real capital loss.** Mitigations: deterministic risk engine, hard limits, circuit breakers, start tiny, graduate autonomy only on evidence, kill switch.
- **Tail/black-swan events, gaps, flash crashes.** LLMs reason poorly about regime breaks. Mitigations: volatility-aware position caps, automatic de-risking on regime-shift detection, "halt on the weird" — when the world looks unlike training/backtest distribution, freeze and ask the human.
- **Overfitting in backtests.** The classic way to feel rich and go broke. Mitigations: out-of-sample/walk-forward validation, transaction-cost + slippage realism, calibration over raw return as the metric, skepticism about any strategy that looks too good.

### 6.2 AI-specific
- **Hallucination / fabricated reasoning.** Mitigations: structured outputs, evidence must cite real ingested Signals (no evidence → no trade), cross-check LLM claims against deterministic data, confidence calibration tracking.
- **Prompt injection via news/social.** A malicious headline could try to instruct the model. **Treat all ingested text as untrusted data, never as instructions.** Strict separation of system prompt vs retrieved content; sanitize; the risk engine is the backstop because it ignores narrative entirely.
- **Model drift / silent provider changes.** Pin versions, record them, re-validate calibration on model upgrades.

### 6.3 Technical / operational
- **Order idempotency & double-submission.** Client order IDs, dedup, reconciliation. A retry bug can double your position.
- **State desync with broker.** Broker is ground truth; reconcile continuously; halt on unexplained divergence.
- **Connectivity / partial outages.** What happens to open positions if data dies mid-trade? Define **fail-safe defaults** (e.g., on feed loss beyond N seconds, stop opening new positions; optionally protect open ones). Never fail *open* into more risk.
- **Latency & rate limits.** Respect exchange limits; backoff; queue. Our timescale tolerates this, but rate-limit bans during volatility are dangerous — budget headroom.
- **Clock skew & timezones.** NTP-sync; store UTC; market-hours awareness for equities.

### 6.4 Security
- **Key compromise = direct theft.** Encrypted secrets, withdrawal-disabled API keys, IP allowlists where supported, MFA on console, no keys in logs/repo, rotate regularly.
- **Console access control.** The dashboard can move money — auth it like a bank, not a hobby app.

### 6.5 Regulatory / legal
- **This depends heavily on jurisdiction and whether others' money is involved.** Single-operator, own-capital, own-accounts is the simplest posture. The moment you manage others' funds, broadcast signals as advice, or take custody, you enter advisor/broker/MSB regulatory territory. **Constraint: keep it single-operator/own-capital until deliberately deciding otherwise, with counsel.** Maintain records (the audit trail doubles as compliance evidence). Honor exchange/broker API ToS and market-data licensing (redistribution rules matter for the UI).

### 6.6 Psychological / product
- **Automation complacency.** A smooth UI breeds over-trust. Mitigation: surface uncertainty prominently, force periodic operator engagement, show calibration honestly (including when the AI is miscalibrated).
- **Optimizing the wrong metric.** Chasing return early invites blow-ups. Hold the line on calibration/auditability as the north star.

---

## 7. Operator Workflows

### 7.1 Morning / session start
Operator opens the terminal → **System Status** panel confirms feeds live, broker connected, risk limits loaded, reconciliation clean. Overnight digest: what the AI observed afterhours, theses opened/invalidated, shadow decisions and how they'd have done.

### 7.2 The core loop — Decision Queue
The heart of the UX. A live queue of Decision Objects awaiting action. Each card shows: thesis (one line), instrument, proposed side/size, **confidence + calibration context** ("the model is historically 60% reliable at this confidence"), the evidence (clickable to source news/signals), risk (max loss, stop, invalidation), and historical analogue. Operator actions: **Approve / Approve-with-edits (resize) / Reject (+reason) / Snooze / Convert-to-alert.** Rejections with reasons are training gold — capture them.

### 7.3 Investigation
Operator clicks any instrument → drill-down: chart, related news stream, current/closed positions, the open theses touching it, and a chat pane to interrogate the AI ("why are you bearish here? what would change your mind?"). The AI answers grounded in the same retrieved evidence.

### 7.4 Monitoring open risk
**Portfolio panel:** positions, live P&L, exposure heat (by asset/sector/correlation), distance-to-stop, margin. **Alerts** when a thesis nears invalidation or risk thresholds approach.

### 7.5 Intervention
One-click **flatten position / halt instrument / global kill switch.** Always reachable, never more than one action away. Confirm on global kill, instant on single-position.

### 7.6 Review / retrospective
**Audit & Journal:** replay any past Decision — exactly what it saw, why, what happened, realized vs predicted. Weekly calibration report. Tag trades, annotate lessons. This closes the learning loop that makes the operator + system improve together.

### 7.7 Strategy lab
Separate workspace: configure/backtest strategies and prompt/model variants, compare on out-of-sample calibration and risk-adjusted return, then promote a config from Observe → Paper → Assisted with an explicit gate at each step.

---

## 8. The Terminal UI

Panels (composable, draggable, keyboard-navigable — think tiling window manager):
- **Command bar** (top): `/buy`, `/halt`, `/explain`, `/backtest`, fuzzy command palette. Keyboard-first.
- **Decision Feed** — the queue (§7.2).
- **News Stream** — live, relevance-scored, instrument-linked, sentiment-tagged.
- **Market Watch** — quotes, sparklines, movers.
- **Chart** — TradingView lightweight-charts, with AI annotations (entries, theses, invalidation levels).
- **AI Console** — the model's live "stream of consciousness" (rate-limited, summarized) + interactive chat. The signature panel; makes the system feel alive and transparent.
- **Portfolio / Risk** — positions, P&L, exposure heat, limits usage.
- **Trade Log** — fills, orders, reconciliation status.
- **System Status / Diagnostics** — feed health (with freshness timers), latencies, error rates, rate-limit budgets, kill-switch state.

**Design rules:** every data panel shows freshness/staleness; uncertainty is always visible; the kill switch is always one action away; dense but not cluttered; dark, monospaced, fast. Real-time via WebSocket subscriptions to bus topics. Degrade gracefully — a dead feed greys its panel rather than crashing the app.

---

## 9. Phased Implementation Roadmap

Each phase ends in something usable and de-risks the next. **No real money until Phase 4, and only after calibration evidence.**

### Phase 0 — Foundations (skeleton & contracts)
- Repo, modular-monolith scaffold, the event bus, the **Decision Object + core schemas**, Postgres, config/secrets, structured logging, CI.
- One real read-only data feed end-to-end → bus → DB → a trivial UI panel.
- *Exit:* an event flows from source to screen, persisted and auditable.

### Phase 1 — Sense (ingestion & UI shell)
- Market data + news ingestion with provenance + normalization. Signal/feature store basics. Terminal UI shell with live News, Market Watch, Chart, System Status panels.
- *Exit:* operator watches a live, normalized, healthy multi-feed terminal. No AI yet.

### Phase 2 — Think (reasoning, read-only)
- Reasoning engine producing structured Decision Objects in **Observe mode** (shadow only, no execution). RAG context, historical-analogue retrieval, AI Console panel, Decision Feed (display-only).
- *Exit:* the AI narrates the market and emits well-formed, evidence-cited shadow decisions you can inspect.

### Phase 3 — Simulate (risk + paper execution + backtest)
- Deterministic **risk engine**, paper execution adapter, portfolio/ledger, **backtesting engine** with point-in-time correctness, calibration reporting. Modes: Observe + Paper + Assisted (approval queue against paper account).
- *Exit:* full pipeline runs on paper; you can backtest strategies/prompts and measure calibration. **This is the real product before money is at stake.**

### Phase 4 — Trade (live, tightly bounded)
- Live broker/exchange adapters (one crypto exchange first — simpler APIs, 24/7, smaller starting size). Idempotency, reconciliation, hardened secrets, MFA console. **Assisted mode only**, micro position sizes, every order human-approved.
- *Exit:* small real trades execute correctly, reconcile, and are fully audited. Graduate to Semi-autonomous *only* on demonstrated calibration.

### Phase 5 — Scale & autonomy
- Add equities adapter (market hours, settlement, PDT rules), more venues, multi-instrument theses, Semi-autonomous → Supervised-autonomous modes with bounded envelopes, advanced risk (correlation/portfolio optimization), richer Strategy Lab, A/B of models.
- *Exit:* multi-market, partially autonomous, still gated and observable.

### Phase 6 — Harden & extend
- Performance, extraction of hot modules to services if needed, advanced observability, optional multi-account, disaster recovery, and the "additional features" of §10 as warranted.

---

## 10. Proposed Additional Features (beyond the brief)

These meaningfully raise the platform's ceiling:

1. **Calibration tracking & reliability scoring** *(high priority).* Continuously measure predicted-confidence vs realized-outcome; show the operator how trustworthy the AI is at each confidence level. Turns "the AI is confident" into a quantified, earned signal. This is what separates a toy from a trustworthy instrument.
2. **Historical analogue retrieval.** "This setup resembles these N past situations; here's how they resolved." Grounds reasoning in evidence and reads as eerily smart.
3. **Thesis lifecycle management.** Persistent beliefs with explicit invalidation conditions, auto-flagged when violated. Makes the system coherent over time rather than reactive.
4. **Pre-mortem / red-team agent.** A second AI role whose only job is to argue *against* each proposed trade and surface what would make it wrong. Cheap insurance against one-sided reasoning and overconfidence.
5. **"Explain this market" on demand.** Operator selects any move; AI synthesizes the likely drivers from the news/signal stream with citations.
6. **Decision replay & counterfactuals.** Re-run a past decision under a different model/prompt to see what would've changed — powering both debugging and model selection.
7. **Operator feedback loop as data.** Every approve/reject/edit with reason becomes a labeled dataset for evaluation and (eventually) fine-tuning or prompt improvement.
8. **Scenario / stress simulator.** "What happens to the book if BTC drops 20% in an hour / if rates spike?" Stress the portfolio against shocks before they happen.
9. **News-deduplication & narrative clustering.** Collapse 50 headlines about one event into one tracked narrative with momentum, instead of spamming the feed.
10. **Cost & slippage accounting as first-class.** Track fees, spread, and realized slippage per trade; feed them back into both backtests and live sizing. Ignoring these is the #1 reason paper success dies in live.
11. **Alerting / notification spine** *(maybe ScheduleWakeup-style cadences for afterhours monitoring).* Push to the operator when something needs a human — by definition the system runs when you're not watching.
12. **Privacy/PII & content licensing guardrails** for ingested data (boring, but keeps you legal on redistribution).

---

## 11. Challenges to the Original Brief

Stated plainly, as requested:

- **"Optionally executing trades autonomously" should not be a launch capability.** Autonomy must be *earned* via demonstrated calibration, never a default. Reframed as a graduated privilege (§5). This is the single biggest risk in the brief.
- **"Generating trade ideas" with an LLM is the easy 20%; *trusting and controlling* them is the hard, valuable 80%.** The investment center of gravity should be the risk engine, audit trail, and calibration — not the idea generator. Anyone can prompt a model to be bullish.
- **Returns are the wrong early metric.** Optimizing P&L on small samples manufactures overfit, overconfident strategies that blow up. Optimize calibration and auditability first; returns follow from a trustworthy process.
- **"Complete product, not a script" cuts both ways** — resist over-engineering into premature microservices. A disciplined modular monolith is the *more* professional choice for a single-operator product at this stage.
- **Crypto before equities.** Despite equities being "more traditional," crypto's 24/7 markets, simpler/uniform APIs, no market-hours/settlement/PDT complexity, and tiny-size accessibility make it the right *first* live target. Equities are Phase 5.
- **The LLM must never compute the numbers it shouldn't.** Sizing, risk, and statistics are deterministic code. Architecturally enforce the separation of duties (§4.5) or you inherit hallucinated math with real money behind it.
- **Regulatory posture is a design constraint, not a footnote.** Staying single-operator/own-capital is what keeps the project simple and legal; any move beyond that is a deliberate, counsel-reviewed decision (§6.5).

---

## 12. Immediate Next Steps (decisions needed before Phase 0)

### Decision log

| # | Decision | Status | Resolution (2026-06-09) |
|---|---|---|---|
| 1 | **Scope** — who uses it, whose capital | ✅ **LOCKED** | **Single-operator, own-capital.** Simplest regulatory posture; stays out of advisor/broker/custody territory. Any change is a deliberate, counsel-reviewed decision. |
| 2 | **First market & venue** | ✅ **LOCKED** | **Crypto first; equities deferred to Phase 5.** Primary venue: **Coinbase Advanced Trade** (US-regulated, free realtime WS, scoped/withdrawal-disabled keys); **Kraken** documented alternate. Provisional/swappable via CCXT — execution venue not truly committed until Phase 4; Phase 0–3 needs only the free realtime market-data feed. |
| 3 | **Tech stack** | ✅ **LOCKED** | **Python core + TypeScript/React terminal + Postgres-centric storage (Timescale + pgvector) + event bus.** Per §4. |
| 4 | **Data sources** (market-data + news vendors) | ✅ **LOCKED** | **Free-tier-first layered stack** (see Appendix A). Native exchange WS + CCXT for market data; CoinGecko/CryptoPanic/Finnhub free tiers + RSS for reference & news. Social sentiment flagged-off. Paid vendors deferred to Phase 5+. |
| 5 | **Non-negotiables** | ✅ **LOCKED (binding)** | Deterministic risk engine as authoritative gatekeeper · Decision Object as central artifact · calibration as north star · kill switch from day one. Confirmed binding — no implementation may violate these. |
| 6 | **Autonomy doctrine** | ✅ **LOCKED** | **Balanced graduation gates** (see Appendix B). Calibration (ECE) is the primary gate; returns are only a sanity floor. Demotion triggers kept at full strength. |

### Still open before Phase 0
- **None blocking.** All six decisions are resolved. Phase 0 is fully unblocked.
- *Deferred, non-blocking:* re-confirm the Coinbase-vs-Kraken venue pick before Phase 4 (live execution), since Phase 0–3 only consumes the free realtime feed.

With #1–#3 locked, **Phase 0 can begin in parallel** with resolving #4–#6, since the scaffold, event bus, and Decision Object schema don't depend on the open items:

> **Phase 0 kickoff:** modular-monolith scaffold (Python) · event bus · Decision Object + core schemas (Pydantic, with generated TS types) · Postgres + config/secrets · structured logging + CI · one read-only crypto feed flowing source → bus → DB → a trivial UI panel.

---

---

## Appendix A — Data & News Vendor Stack (Decision #4, LOCKED)

**Posture:** free-tier-first, optimize for **free realtime coverage** — not for minimizing the number of vendors. Layer as many free realtime surfaces as add value; breadth is fine. Keep recurring cost near $0 while the product is unproven and pay for premium coverage only when a concrete gap appears. Everything sits behind adapters (`MarketDataSource`, `NewsSource`) so any single surface can be upgraded to a paid tier later without a rewrite — the door to upgrading stays open by construction.

**Key insight:** for crypto, the execution exchange's own WebSocket feed is the *authoritative, free* market-data source for the instruments you actually trade. We don't need a paid market-data vendor to start — we need normalization and good news/macro coverage.

| Layer | Build-phase choice (free) | Upgrade path (Phase 5+) |
|---|---|---|
| **Market data** — prices, OHLCV, order books | Native exchange WS/REST + **CCXT** (normalizes 100+ venues) | **CoinAPI** or **Kaiko‑Amberdata** for institutional tick/historical depth |
| **Reference/metadata** — broad cross-asset, bundled news | **CoinGecko API** free tier (~10k calls/mo) | CoinGecko Pro |
| **News stream** | **CryptoPanic** (crypto aggregator + sentiment) + **RSS** (CoinDesk, The Block) | The TIE / Benzinga |
| **Macro / economic calendar** | **Finnhub** free tier (news + econ calendar) | Trading Economics |
| **On-chain** | Deferred | Amberdata / Glassnode |
| **Social sentiment** | **Flagged OFF by default** — prompt-injection vector + mostly noise | LunarCrush (opt-in, behind a flag) |

**Rules:**
- All ingested text is **untrusted data, never instructions** (§6.2). Social sentiment stays opt-in precisely because it is the easiest injection surface.
- Every datum carries provenance + ingest timestamp (§2.1).
- Respect each vendor's rate limits and market-data **redistribution/licensing** terms — relevant once the UI displays third-party data (§6.5).
- Free tiers are rate-limited; budget headroom and cache aggressively (Redis) so a volatility spike doesn't exhaust quota.

---

## Appendix B — Autonomy Graduation Gates (Decision #6, LOCKED — "Balanced" profile)

Gates a model/strategy config must clear to earn the next autonomy mode (§5). **Calibration error (ECE)** — does stated confidence match realized outcomes — is the *primary* gate. Returns are only a sanity floor; we are not optimizing P&L on small samples (§11). Thresholds below are the **Balanced** profile (roughly half the sample sizes/time windows and slightly looser ECE than the strict default); they are config, tune as evidence accumulates.

| Transition | Min sample | Calibration (ECE) | Regime coverage | Risk discipline | Operator reject rate | Perf floor | Operational |
|---|---|---|---|---|---|---|---|
| **Observe → Paper** | 50 resolved shadow decisions | ≤ 0.18 | ≥1 | — | — | — | schemas + audit trail working |
| **Paper → Assisted** *(first real $)* | 100 paper trades, ≥14 days | ≤ 0.12 | ≥2 | 0 limit breaches | — | Sharpe > 0 *net of modeled fees + slippage* | secrets hardened, **kill-switch drill passed**, recon clean |
| **Assisted → Semi-auto** | 50 live assisted trades, ≥30 days | ≤ 0.10, stable | ≥2 | 0 breaches, 0 recon/idempotency errors | ≤ 25% (high reject = not trusted) | net-positive after *real* costs | execution envelope defined & tested |
| **Semi-auto → Supervised** | 100 semi-auto trades, ≥45 days | ≤ 0.10 sustained | ≥2, incl. one stress event | 0 breaches; auto-halt fired correctly when triggered | escalation accuracy high | risk-adjusted ≥ target | broader limits explicitly signed off |

**Graduation is not one-way — demotion triggers stay at full strength regardless of profile.** Any of the following automatically knocks the system down a mode until it re-qualifies:
- **Calibration drift** — rolling ECE degrades past the gate for the current mode.
- **Drawdown breach** — realized drawdown exceeds the configured limit.
- **Reconciliation / idempotency errors** — any unexplained divergence from broker ground truth.
- **Model/prompt version change** — pinned version changes ⇒ forced re-validation (calibration can silently shift on a model upgrade, §6.2).
- **Regime break detected** — the world looks unlike the validation distribution ⇒ "halt on the weird" (§6.1), de-risk and fall back to Assisted.

Keeping the safety rails full-strength is what makes the faster Balanced ramp acceptable: we let a model *climb* faster, but it still *falls* the instant the evidence turns.

---

*End of v0.1. All six §12 decisions are LOCKED. Phase 0 is fully unblocked. Revise as Phase exits reveal new constraints (and re-confirm the live execution venue before Phase 4).*
