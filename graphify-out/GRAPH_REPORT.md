# Graph Report - .  (2026-06-12)

## Corpus Check
- 193 files · ~73,241 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1838 nodes · 5547 edges · 101 communities (91 shown, 10 thin omitted)
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 1851 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Calibration Engine|Calibration Engine]]
- [[_COMMUNITY_Price Alert Generation|Price Alert Generation]]
- [[_COMMUNITY_Feed Infrastructure|Feed Infrastructure]]
- [[_COMMUNITY_Coinbase Feed|Coinbase Feed]]
- [[_COMMUNITY_Decision Generation|Decision Generation]]
- [[_COMMUNITY_Core Settings & Schemas|Core Settings & Schemas]]
- [[_COMMUNITY_Domain Models|Domain Models]]
- [[_COMMUNITY_Event Store Tests|Event Store Tests]]
- [[_COMMUNITY_Paper Executor|Paper Executor]]
- [[_COMMUNITY_Bus Core|Bus Core]]
- [[_COMMUNITY_Outcome Resolution|Outcome Resolution]]
- [[_COMMUNITY_Portfolio Ledger|Portfolio Ledger]]
- [[_COMMUNITY_News Feed|News Feed]]
- [[_COMMUNITY_Architecture Decision Records|Architecture Decision Records]]
- [[_COMMUNITY_Equity Feed|Equity Feed]]
- [[_COMMUNITY_Gateway Tests|Gateway Tests]]
- [[_COMMUNITY_Risk Engine|Risk Engine]]
- [[_COMMUNITY_Frontend Dependencies|Frontend Dependencies]]
- [[_COMMUNITY_WebSocket Broadcaster|WebSocket Broadcaster]]
- [[_COMMUNITY_Feed Router|Feed Router]]
- [[_COMMUNITY_Connection Management|Connection Management]]
- [[_COMMUNITY_Calibration API Routes|Calibration API Routes]]
- [[_COMMUNITY_LLM Cache|LLM Cache]]
- [[_COMMUNITY_Backtest Runner|Backtest Runner]]
- [[_COMMUNITY_Frontend Type Definitions|Frontend Type Definitions]]
- [[_COMMUNITY_Thesis Generation|Thesis Generation]]
- [[_COMMUNITY_Watchlist & Event Types|Watchlist & Event Types]]
- [[_COMMUNITY_Gateway App|Gateway App]]
- [[_COMMUNITY_Portfolio Tests|Portfolio Tests]]
- [[_COMMUNITY_LLM Provider Interface|LLM Provider Interface]]
- [[_COMMUNITY_Decision Generator Tests|Decision Generator Tests]]
- [[_COMMUNITY_In-Process Bus|In-Process Bus]]
- [[_COMMUNITY_LLM Provider Factory|LLM Provider Factory]]
- [[_COMMUNITY_TypeScript Config|TypeScript Config]]
- [[_COMMUNITY_Watchlist Tests|Watchlist Tests]]
- [[_COMMUNITY_Bus Unit Tests|Bus Unit Tests]]
- [[_COMMUNITY_Ring Buffer Store|Ring Buffer Store]]
- [[_COMMUNITY_Frontend Structure|Frontend Structure]]
- [[_COMMUNITY_Backtest Tests|Backtest Tests]]
- [[_COMMUNITY_Equity Feed Router|Equity Feed Router]]
- [[_COMMUNITY_Frontend TS Config|Frontend TS Config]]
- [[_COMMUNITY_Price Quantization|Price Quantization]]
- [[_COMMUNITY_Decision API|Decision API]]
- [[_COMMUNITY_Bus Interface|Bus Interface]]
- [[_COMMUNITY_Position Sizing|Position Sizing]]
- [[_COMMUNITY_Frontend App Root|Frontend App Root]]
- [[_COMMUNITY_Logging Config|Logging Config]]
- [[_COMMUNITY_Event Pattern Matching|Event Pattern Matching]]
- [[_COMMUNITY_Market Watch Panel|Market Watch Panel]]
- [[_COMMUNITY_Feed Base|Feed Base]]
- [[_COMMUNITY_Signal State Hook|Signal State Hook]]
- [[_COMMUNITY_Event Stream Hooks|Event Stream Hooks]]
- [[_COMMUNITY_Decision Queue Panel|Decision Queue Panel]]
- [[_COMMUNITY_Thesis Feed Panel|Thesis Feed Panel]]
- [[_COMMUNITY_Calibration Hook|Calibration Hook]]
- [[_COMMUNITY_Watchlist Hook|Watchlist Hook]]
- [[_COMMUNITY_Decisions Hook|Decisions Hook]]
- [[_COMMUNITY_Signal Feed Panel|Signal Feed Panel]]
- [[_COMMUNITY_Market Ticks Hook|Market Ticks Hook]]
- [[_COMMUNITY_Theses Hook|Theses Hook]]
- [[_COMMUNITY_Watchlist Panel|Watchlist Panel]]
- [[_COMMUNITY_Calibration Panel|Calibration Panel]]
- [[_COMMUNITY_Groq LLM Provider|Groq LLM Provider]]
- [[_COMMUNITY_Mistral LLM Provider|Mistral LLM Provider]]
- [[_COMMUNITY_OpenAI LLM Provider|OpenAI LLM Provider]]
- [[_COMMUNITY_Anthropic LLM Provider|Anthropic LLM Provider]]
- [[_COMMUNITY_Portfolio Hook|Portfolio Hook]]
- [[_COMMUNITY_Portfolio Panel|Portfolio Panel]]
- [[_COMMUNITY_Order Idempotency Tests|Order Idempotency Tests]]
- [[_COMMUNITY_Event Publishing|Event Publishing]]
- [[_COMMUNITY_TS Project References|TS Project References]]
- [[_COMMUNITY_Autonomy Level|Autonomy Level]]
- [[_COMMUNITY_Panel Shell Component|Panel Shell Component]]
- [[_COMMUNITY_Thesis Invalidator|Thesis Invalidator]]
- [[_COMMUNITY_Utility Bool|Utility Bool]]
- [[_COMMUNITY_Code of Conduct|Code of Conduct]]
- [[_COMMUNITY_Frontend Entry Point|Frontend Entry Point]]

## God Nodes (most connected - your core abstractions)
1. `EventEnvelope` - 318 edges
2. `EventType` - 307 edges
3. `Bus` - 172 edges
4. `Subscription` - 135 edges
5. `ModeController` - 118 edges
6. `AutonomyMode` - 111 edges
7. `WatchlistManager` - 76 edges
8. `Portfolio` - 72 edges
9. `Side` - 71 edges
10. `PaperExecutor` - 62 edges

## Surprising Connections (you probably didn't know these)
- `Any` --uses--> `EventType`  [INFERRED]
  gateway/routes/events.py → core/schemas/events.py
- `int` --uses--> `EventType`  [INFERRED]
  gateway/routes/events.py → core/schemas/events.py
- `Request` --uses--> `EventType`  [INFERRED]
  gateway/routes/events.py → core/schemas/events.py
- `str` --uses--> `EventType`  [INFERRED]
  gateway/routes/events.py → core/schemas/events.py
- `bool` --uses--> `Broadcaster`  [INFERRED]
  tests/gateway/test_broadcaster.py → gateway/broadcaster.py

## Hyperedges (group relationships)
- **Decision Processing Pipeline** — concept_risk_engine_gate, concept_decision_object, concept_graduated_autonomy, concept_separation_duties [INFERRED 0.85]
- **Calibration-Gated Autonomy Promotion Loop** — concept_ece_calibration, concept_appendix_b_gates, concept_graduated_autonomy [EXTRACTED 0.95]
- **Multi-Layer Safety Envelope** — concept_kill_switch, concept_risk_engine_gate, concept_observe_restart [INFERRED 0.85]

## Communities (101 total, 10 thin omitted)

### Community 0 - "Calibration Engine"
Cohesion: 0.06
Nodes (77): _bucketed(), CalibrationEngine, compute_ece(), Any, EventEnvelope, float, int, str (+69 more)

### Community 1 - "Price Alert Generation"
Cohesion: 0.05
Nodes (48): PriceAlertGenerator, Price alert generator.  Subscribes to market.tick and publishes signal.created, Watches market.tick events and emits signal.created on price conditions., AlertSettings, bus_and_gen(), _collect_signals(), Tests for PriceAlertGenerator.  Uses a real InProcessBus so the full publish →, TestFirstTick (+40 more)

### Community 2 - "Feed Infrastructure"
Cohesion: 0.06
Nodes (38): Any, Bus, bytes, str, Any, datetime, EventEnvelope, str (+30 more)

### Community 3 - "Coinbase Feed"
Cohesion: 0.05
Nodes (30): CoinbaseFeed, CoinbaseFeed — Coinbase Advanced Trade WebSocket market-data feed.  Connects t, Parse one raw WebSocket message and publish any resulting envelopes., Subscribes to the Coinbase Advanced Trade WebSocket ticker channel     and publ, Run forever, reconnecting with exponential backoff on any disconnect., Cancel the owning task to stop. This method is a hook for cleanup., One connection lifetime. Raises on any error so tenacity can retry., CoinbaseNormalizer (+22 more)

### Community 4 - "Decision Generation"
Cohesion: 0.09
Nodes (51): _as_uuid(), DecisionGenerator, Decision generator.  Subscribes to thesis.created. For each new active thesis,, Parse a thesis/id field into a UUID, or None if absent/malformed., build_decision_messages(), Prompt templates for decision generation., DecisionSettings, bus() (+43 more)

### Community 5 - "Core Settings & Schemas"
Cohesion: 0.07
Nodes (52): Any, AutonomyMode, CalibrationSettings, EventEnvelope, LLMProvider, Path, PortfolioSettings, RiskSettings (+44 more)

### Community 6 - "Domain Models"
Cohesion: 0.10
Nodes (42): BaseModel, Enum, Order, _ParkedDecision, Any, AutonomyMode, bool, Bus (+34 more)

### Community 7 - "Event Store Tests"
Cohesion: 0.07
Nodes (25): _envelope(), Tests for SqliteEventStore.recent() against a real in-memory SQLite DB., store(), TestRange, TestRecent, Connection, str, Connection (+17 more)

### Community 8 - "Paper Executor"
Cohesion: 0.12
Nodes (43): PaperExecutor, Clear all parked decisions, emitting an audited decision.expired each., _approved(), bus(), portfolio(), The decision → order → fill chain carries a deterministic client_order_id., A re-delivered approval (same decision id) must not produce a second fill., Closing fills carry a distinct close-intent client_order_id for attribution. (+35 more)

### Community 9 - "Bus Core"
Cohesion: 0.14
Nodes (36): Bus, Opaque handle returned by subscribe(). Pass back to unsubscribe().      patter, De-register a handler. Safe to call with an already-removed sub., Graceful shutdown — drain in-flight work and release resources., Subscription, Bus, CalibrationSettings, _Pending (+28 more)

### Community 10 - "Outcome Resolution"
Cohesion: 0.15
Nodes (30): OutcomeResolver, EventEnvelope, Re-track unresolved decision.proposed envelopes from the event store.         T, Replay historical tick / thesis-invalidation events (in event_time         orde, bus(), _proposed(), OutcomeResolver tests — event-time-driven decision scoring., A proposal is stamped with the live mode read from the shared controller,     s (+22 more)

### Community 11 - "Portfolio Ledger"
Cohesion: 0.10
Nodes (19): Portfolio, Bus, datetime, Decimal, EventEnvelope, int, object, PortfolioSettings (+11 more)

### Community 12 - "News Feed"
Cohesion: 0.12
Nodes (26): AsyncBaseTransport, AsyncClient, Bus, NewsFeedSettings, str, WatchlistManager, MockTransport, NewsFeed (+18 more)

### Community 13 - "Architecture Decision Records"
Cohesion: 0.13
Nodes (39): ADR-001: Event Bus Contract, ADR-002: SQLite Local Storage, ADR-003: API Key Security Policy, ADR-004: Graduated Autonomy Model, ADR-005: Exchange Feed Architecture, ADR-006: LLM Thesis Layer, ADR-007: Roadmap Rescope Phase 4, ADR-008: Single Source of Truth for Autonomy Mode (+31 more)

### Community 14 - "Equity Feed"
Cohesion: 0.10
Nodes (22): alpaca_snapshot_to_payload(), EquityFeed, _is_market_open(), EquityFeed — REST polling stub for equity market data.  Polls the configured p, REST polling equity feed.  subscribe()/unsubscribe() are thread-safe., Seconds until the next NYSE open (9:30 ET on a weekday)., Map one symbol's Alpaca snapshot to the optional market.tick payload     fields, _seconds_until_open() (+14 more)

### Community 15 - "Gateway Tests"
Cohesion: 0.09
Nodes (15): client(), _lifespan(), Tests for the FastAPI app — HTTP endpoints and WebSocket route.  Uses a test l, Publish to the bus while a client is connected; verify it arrives., TestCalibrationEndpoints, TestHealthEndpoint, TestModeEndpoints, TestRecentEventsEndpoint (+7 more)

### Community 16 - "Risk Engine"
Cohesion: 0.16
Nodes (32): RiskEngine, bus(), portfolio(), _proposed_at(), _proposed_envelope(), RiskEngine integration tests., A SHIB-class price must yield a real stop, not 0.00 from cent rounding., When cash is nearly depleted, a trade that can't be afforded is rejected     ra (+24 more)

### Community 17 - "Frontend Dependencies"
Cohesion: 0.06
Nodes (35): dependencies, class-variance-authority, clsx, lucide-react, @radix-ui/react-dialog, @radix-ui/react-dropdown-menu, @radix-ui/react-label, @radix-ui/react-scroll-area (+27 more)

### Community 18 - "WebSocket Broadcaster"
Cohesion: 0.13
Nodes (15): Broadcaster, broadcaster(), _drain(), _envelope(), FakeWebSocket, Unit tests for Broadcaster.  Uses FakeWebSocket instead of a real FastAPI WebS, A client stalled mid-send must not delay publish() — the publisher         (Kra, One congested client must not delay delivery to healthy clients. (+7 more)

### Community 19 - "Feed Router"
Cohesion: 0.17
Nodes (14): FeedRouter, _added_envelope(), _mock_watchlist(), Tests for FeedRouter: routing watchlist changes to the correct feed adapter., Return a mock WatchlistManager with preset active_instruments and markets., _removed_envelope(), _setup(), TestBootstrap (+6 more)

### Community 20 - "Connection Management"
Cohesion: 0.08
Nodes (16): _ClientChannel, EventEnvelope, int, object, str, Stop the writer task without awaiting (for the sync disconnect path)., Stop the writer task and await its teardown (for graceful shutdown)., Subscribe to the bus. Call once during app startup. (+8 more)

### Community 21 - "Calibration API Routes"
Cohesion: 0.08
Nodes (26): Any, Request, str, Any, int, Request, str, Request (+18 more)

### Community 22 - "LLM Cache"
Cohesion: 0.17
Nodes (22): Exception, CachingProvider, JsonFileLLMCache, LLMCacheMiss, prompt_key(), Raised in replay mode when no recorded response exists for a prompt., Durable prompt-hash → response store. Loads lazily, writes atomically., CountingProvider (+14 more)

### Community 23 - "Backtest Runner"
Cohesion: 0.14
Nodes (22): ArgumentParser, _build_parser(), _load_source_events(), main(), _parse_ts(), datetime, EventEnvelope, int (+14 more)

### Community 24 - "Frontend Type Definitions"
Cohesion: 0.07
Nodes (26): AutonomyMode, Decision, DecisionOutcome, DecisionStatus, EventEnvelope, EventType, Evidence, EvidenceStance (+18 more)

### Community 25 - "Thesis Generation"
Cohesion: 0.18
Nodes (19): Any, bool, Bus, datetime, EventEnvelope, LLMProvider, str, ThesisSettings (+11 more)

### Community 26 - "Watchlist & Event Types"
Cohesion: 0.16
Nodes (14): EventType, NamedTuple, Bus, WatchlistSettings, WatchlistManager — runtime instrument registry.  Loads the persisted watchlist, WatchlistSettings, Connection, str (+6 more)

### Community 27 - "Gateway App"
Cohesion: 0.16
Nodes (15): create_app(), default_lifespan(), Any, FastAPI, FastAPI gateway — HTTP + WebSocket server.  The gateway is the single entry po, Returns a configured FastAPI application.      Pass a custom lifespan in tests, _register_routes(), Broadcaster (+7 more)

### Community 28 - "Portfolio Tests"
Cohesion: 0.21
Nodes (24): bus(), _fill_event(), portfolio(), Portfolio ledger tests., The short leg must book the entry fee into realized P&L too., A loss realized yesterday must not count against today's daily breaker., A fresh portfolio replays the persisted fill history into the same cash,     op, Rehydration is the live fill path replayed: both end in identical state. (+16 more)

### Community 29 - "LLM Provider Interface"
Cohesion: 0.18
Nodes (15): LLMProvider, Message, Send messages and return the assistant's text response., LLM record/replay cache.  `CachingProvider` wraps any `LLMProvider` and keys res, LLMProvider, AnthropicProvider, OllamaProvider, OpenAICompatibleProvider (+7 more)

### Community 30 - "Decision Generator Tests"
Cohesion: 0.17
Nodes (18): datetime, EventEnvelope, InProcessBus, int, Message, str, ThesisGenerator, bus() (+10 more)

### Community 31 - "In-Process Bus"
Cohesion: 0.15
Nodes (15): Bus, Register handler for events matching pattern. Returns a Subscription., InProcessBus, _safe_call(), EventStore, Append-only event persistence backend., Release any held resources., Handler (+7 more)

### Community 32 - "LLM Provider Factory"
Cohesion: 0.17
Nodes (20): create_provider(), _resolve_key(), LLMSettings, Tests for JSON extraction and the LLM provider factory., test_create_provider_anthropic(), test_create_provider_groq(), test_create_provider_mistral(), test_create_provider_ollama() (+12 more)

### Community 33 - "TypeScript Config"
Cohesion: 0.09
Nodes (21): compilerOptions, allowImportingTsExtensions, baseUrl, isolatedModules, jsx, lib, module, moduleDetection (+13 more)

### Community 34 - "Watchlist Tests"
Cohesion: 0.19
Nodes (9): str, WatchlistSettings, _make_bus(), Tests for WatchlistManager., _settings(), TestActiveInstruments, TestAdd, TestRemove (+1 more)

### Community 35 - "Bus Unit Tests"
Cohesion: 0.23
Nodes (8): bus(), _envelope(), Unit tests for InProcessBus and pattern matching.  All tests use InMemoryEvent, Handler must see the event already in the store when it fires., store(), TestInProcessBus, InMemoryEventStore, InProcessBus

### Community 36 - "Ring Buffer Store"
Cohesion: 0.17
Nodes (9): The newest `limit` events of the given types, in chronological order., All events of the given types within [start, end], in chronological         ord, Delete events older than `before` for the given types. Returns rows deleted., Durably write the event. Must be idempotent on duplicate id., Delete events of the given types older than `before`. Returns count deleted., datetime, EventEnvelope, int (+1 more)

### Community 37 - "Frontend Structure"
Cohesion: 0.11
Nodes (17): aliases, components, hooks, lib, ui, utils, iconLibrary, rsc (+9 more)

### Community 38 - "Backtest Tests"
Cohesion: 0.24
Nodes (15): BacktestRunner integration tests.  Replays a scripted event history (ticks + sig, Empty cache + no inner provider: the thesis is skipped, run completes., Record pass with a live-ish provider, then a pure replay reproduces it., _scenario(), ScriptedProvider, _settings(), _signal(), test_observe_replay_produces_shadow_resolutions() (+7 more)

### Community 39 - "Equity Feed Router"
Cohesion: 0.19
Nodes (7): EquityFeed, Bus, WatchlistManager, FeedRouter — maps watchlist changes to feed adapter subscriptions.  When an in, KrakenFeed, str, WatchlistManager

### Community 40 - "Frontend TS Config"
Cohesion: 0.13
Nodes (14): compilerOptions, allowImportingTsExtensions, isolatedModules, lib, module, moduleDetection, moduleResolution, noEmit (+6 more)

### Community 41 - "Price Quantization"
Cohesion: 0.19
Nodes (13): Decimal, int, quantize_price(), Magnitude-aware price quantization.  A single hard-coded tick (e.g. cents) canno, Round ``price`` to ``sig_figs`` significant figures.      Zero passes through un, Tests for magnitude-aware price quantization., A SHIB-class price must not collapse to zero (the bug)., Five-figure prices round to eight sig figs (sub-cent here), not coarser. (+5 more)

### Community 42 - "Decision API"
Cohesion: 0.27
Nodes (13): Request, str, HaltedError, Raised when execution is attempted below ASSISTED authority (e.g. after a halt)., Raised when a parked decision is expired or fails re-validation at execute time., StaleDecisionError, execute_decision(), list_decisions() (+5 more)

### Community 43 - "Bus Interface"
Cohesion: 0.19
Nodes (7): Bus interface — the only coupling point between producers and consumers.  All, InProcessBus — in-process pub/sub backed by a durable EventStore.  Publish con, InMemoryEventStore, EventStore — durable backing for the event bus.  The bus persists every event, Non-durable in-memory store for tests.     Exposes `.events` for direct asserti, EventEnvelope, str

### Community 44 - "Position Sizing"
Cohesion: 0.24
Nodes (10): deterministic_size(), Decimal, float, Deterministic position sizing — fixed-fractional method.  The LLM never contri, Risk-per-trade / stop-distance, capped at max_position.      Example: $10k por, Deterministic sizing tests — most critical unit in the risk layer., test_basic_sizing(), test_raw_wins_when_below_max() (+2 more)

### Community 45 - "Frontend App Root"
Cohesion: 0.20
Nodes (8): AutonomyMode, ConnectionPip(), _ET_TIME_FMT, HaltButton(), _isNyseOpen(), MarketClock(), MODE_STYLES, root

### Community 46 - "Logging Config"
Cohesion: 0.22
Nodes (9): BaseSettings, Config, configure_logging(), LoggingSettings, str, Logging configuration for AFTERHOURS.  Call `configure_logging()` once at appl, Configure structlog + stdlib logging.      level and fmt override env vars (LO, pytest_configure() (+1 more)

### Community 47 - "Event Pattern Matching"
Cohesion: 0.33
Nodes (3): _matches(), True if event_type satisfies pattern.      Patterns:       "*"            — m, TestPatternMatching

### Community 48 - "Market Watch Panel"
Cohesion: 0.31
Nodes (7): formatPct(), formatPrice(), HEADERS, HIDE_BELOW_SM, MarketWatchProps, pctColorClass(), TickItem()

### Community 49 - "Feed Base"
Cohesion: 0.28
Nodes (5): ABC, Feed, Abstract Feed interface. Every exchange/data-source adapter implements this., Run the feed until cancelled. Implementations must reconnect         automatica, Signal a graceful stop. Callers can also cancel the task directly.

### Community 50 - "Signal State Hook"
Cohesion: 0.29
Nodes (6): Action, reducer(), SignalPayload, SignalRow, toRow(), useSignals()

### Community 51 - "Event Stream Hooks"
Cohesion: 0.25
Nodes (6): BACKFILL_REQUESTS, useBackfill(), useCalibration(), useEventStream(), useMarketTicks(), App()

### Community 52 - "Decision Queue Panel"
Cohesion: 0.32
Nodes (5): cn(), DecisionCard(), Props, SideBadge(), StatusBadge()

### Community 53 - "Thesis Feed Panel"
Cohesion: 0.29
Nodes (6): ageLabel(), DIRECTION_CLASSES, DirectionVariant, STATUS_CLASSES, ThesisFeedProps, ThesisItem()

### Community 54 - "Calibration Hook"
Cohesion: 0.29
Nodes (6): CalibrationBucket, CalibrationReport, CalibrationStats, GateCriterion, GatesReport, GateStatus

### Community 55 - "Watchlist Hook"
Cohesion: 0.29
Nodes (5): Action, INITIAL, State, useWatchlist(), WatchlistEntry

### Community 56 - "Decisions Hook"
Cohesion: 0.33
Nodes (6): Action, DecisionRow, EvidenceItem, reducer(), toRow(), useDecisions()

### Community 57 - "Signal Feed Panel"
Cohesion: 0.38
Nodes (5): ageLabel(), BadgeVariant, SignalFeedProps, SignalItem(), typeBadge()

### Community 58 - "Market Ticks Hook"
Cohesion: 0.33
Nodes (4): Action, MarketTickPayload, TickRow, TickState

### Community 59 - "Theses Hook"
Cohesion: 0.40
Nodes (5): Action, reducer(), ThesisRow, toRow(), useTheses()

### Community 60 - "Watchlist Panel"
Cohesion: 0.33
Nodes (4): EntryRow(), FeedDot(), MARKET_COLOR, WatchlistPanelProps

### Community 61 - "Calibration Panel"
Cohesion: 0.40
Nodes (5): CalibrationPanel(), eceColor(), GateCard(), Props, ReliabilityRow()

### Community 62 - "Groq LLM Provider"
Cohesion: 0.33
Nodes (4): float, int, Message, str

### Community 63 - "Mistral LLM Provider"
Cohesion: 0.33
Nodes (4): float, int, Message, str

### Community 64 - "OpenAI LLM Provider"
Cohesion: 0.33
Nodes (4): float, int, Message, str

### Community 65 - "Anthropic LLM Provider"
Cohesion: 0.33
Nodes (4): float, int, Message, str

### Community 66 - "Portfolio Hook"
Cohesion: 0.50
Nodes (3): PortfolioSnapshot, PositionSnapshot, usePortfolio()

## Knowledge Gaps
- **189 isolated node(s):** `str`, `int`, `EventEnvelope`, `str`, `Connection` (+184 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EventType` connect `Core Settings & Schemas` to `Calibration Engine`, `Price Alert Generation`, `Feed Infrastructure`, `Coinbase Feed`, `Decision Generation`, `Domain Models`, `Paper Executor`, `Bus Core`, `Outcome Resolution`, `Portfolio Ledger`, `News Feed`, `Equity Feed`, `Gateway Tests`, `Risk Engine`, `WebSocket Broadcaster`, `Feed Router`, `Calibration API Routes`, `Backtest Runner`, `Thesis Generation`, `Watchlist & Event Types`, `Gateway App`, `Portfolio Tests`, `Decision Generator Tests`, `Watchlist Tests`, `Bus Unit Tests`, `Backtest Tests`, `Equity Feed Router`, `Decision API`, `Thesis Invalidator`?**
  _High betweenness centrality (0.252) - this node is a cross-community bridge._
- **Why does `EventEnvelope` connect `Calibration Engine` to `Price Alert Generation`, `Feed Infrastructure`, `Coinbase Feed`, `Decision Generation`, `Core Settings & Schemas`, `Domain Models`, `Event Store Tests`, `Paper Executor`, `Bus Core`, `Outcome Resolution`, `Portfolio Ledger`, `News Feed`, `Equity Feed`, `Gateway Tests`, `Risk Engine`, `WebSocket Broadcaster`, `Feed Router`, `Backtest Runner`, `Thesis Generation`, `Watchlist & Event Types`, `Gateway App`, `Portfolio Tests`, `Decision Generator Tests`, `Bus Unit Tests`, `Backtest Tests`, `Equity Feed Router`, `Decision API`, `Bus Interface`, `Thesis Invalidator`?**
  _High betweenness centrality (0.185) - this node is a cross-community bridge._
- **Why does `Bus` connect `Bus Core` to `Calibration Engine`, `Price Alert Generation`, `Feed Infrastructure`, `Coinbase Feed`, `Decision Generation`, `Core Settings & Schemas`, `Domain Models`, `Paper Executor`, `Outcome Resolution`, `Portfolio Ledger`, `News Feed`, `Equity Feed`, `Risk Engine`, `Feed Router`, `Thesis Generation`, `Watchlist & Event Types`, `Gateway App`, `Decision Generator Tests`, `In-Process Bus`, `Equity Feed Router`, `Decision API`, `Bus Interface`, `Feed Base`, `Event Publishing`, `Thesis Invalidator`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Are the 241 inferred relationships involving `EventEnvelope` (e.g. with `PriceAlertGenerator` and `TestFirstTick`) actually correct?**
  _`EventEnvelope` has 241 INFERRED edges - model-reasoned connections that need verification._
- **Are the 258 inferred relationships involving `EventType` (e.g. with `PriceAlertGenerator` and `TestFirstTick`) actually correct?**
  _`EventType` has 258 INFERRED edges - model-reasoned connections that need verification._
- **Are the 146 inferred relationships involving `Bus` (e.g. with `PriceAlertGenerator` and `AlertSettings`) actually correct?**
  _`Bus` has 146 INFERRED edges - model-reasoned connections that need verification._
- **Are the 117 inferred relationships involving `Subscription` (e.g. with `PriceAlertGenerator` and `AlertSettings`) actually correct?**
  _`Subscription` has 117 INFERRED edges - model-reasoned connections that need verification._