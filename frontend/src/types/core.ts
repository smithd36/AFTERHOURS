/**
 * Core domain types — TypeScript mirror of core/schemas/*.py
 *
 * Keep in sync with the Pydantic schemas manually until a code-gen pipeline
 * is in place. The Python schemas are the source of truth; update here when
 * they change. All monetary values use `string` (serialised Decimal) to
 * avoid float precision loss in JS.
 */

// ---------------------------------------------------------------------------
// Common
// ---------------------------------------------------------------------------

export type Market = "crypto" | "equity";

export interface Instrument {
  symbol: string; // canonical, e.g. "BTC-USD"
  market: Market;
  base_asset: string;
  quote_asset: string;
  venue_symbols: Record<string, string>; // venue_id -> venue_symbol
}

export interface Provenance {
  source: string;
  source_id: string | null;
  event_time: string; // ISO-8601 UTC
  ingest_time: string; // ISO-8601 UTC
  url: string | null;
}

export interface Money {
  amount: string; // serialised Decimal
  currency: string;
}

// ---------------------------------------------------------------------------
// Signal & Thesis
// ---------------------------------------------------------------------------

export type SignalType =
  | "price_alert"
  | "news"
  | "indicator_crossing"
  | "on_chain"
  | "economic_event"
  | "sentiment"
  | "custom";

export interface Signal {
  id: string; // UUID
  type: SignalType;
  instruments: string[];
  provenance: Provenance;
  payload: Record<string, unknown>; // type-specific; untrusted content
  relevance_score: number | null; // 0–1
  embedding_id: string | null;
}

export type ThesisStatus = "active" | "invalidated" | "expired" | "closed";

export interface Thesis {
  id: string;
  created_at: string;
  updated_at: string;
  instrument: string;
  summary: string;
  body: string;
  status: ThesisStatus;
  invalidation_conditions: string[];
  supporting_signal_ids: string[];
  decision_ids: string[];
}

// ---------------------------------------------------------------------------
// Decision
// ---------------------------------------------------------------------------

export type DecisionStatus =
  | "proposed"
  | "approved"
  | "rejected"
  | "expired"
  | "executing"
  | "executed"
  | "failed";

export type Side = "long" | "short";
export type OrderType = "market" | "limit" | "stop_limit";
export type TimeHorizon = "scalp" | "intraday" | "swing" | "position";
export type HumanActionType =
  | "approved"
  | "rejected"
  | "edited"
  | "snoozed"
  | "converted_to_alert";
export type RiskVerdict = "approved" | "rejected" | "modified";
export type EvidenceStance = "supporting" | "contradicting";

export interface Evidence {
  signal_id: string;
  summary: string;
  stance: EvidenceStance;
}

export interface ModelInfo {
  provider: string;
  model_id: string;
  prompt_hash: string;
  temperature: number;
}

export interface Proposal {
  instrument: string;
  side: Side;
  size_usd: string; // serialised Decimal — computed by sizing code, never LLM
  order_type: OrderType;
  limit_price: string | null;
  time_horizon: TimeHorizon;
}

export interface RiskAssessment {
  max_loss_pct: number;
  stop_price: string | null;
  invalidation_conditions: string[];
  risk_engine_verdict: RiskVerdict;
  rejection_reasons: string[];
  effective_size_multiplier: number; // 0–1; <1 means risk engine scaled down
}

export interface HumanAction {
  actor: string;
  action: HumanActionType;
  note: string | null;
  ts: string;
  edits: Record<string, unknown> | null;
}

export interface Fill {
  fill_id: string;
  order_id: string;
  ts: string;
  price: string;
  quantity: string;
  fee: string;
  fee_currency: string;
}

export interface DecisionOutcome {
  order_ids: string[];
  fills: Fill[];
  realized_pnl: string | null;
  closed_at: string | null;
  slippage_pct: number | null;
}

export interface Decision {
  id: string;
  created_at: string;
  originating_thesis_id: string | null;
  input_signal_ids: string[]; // point-in-time snapshot for audit replay
  model: ModelInfo;
  proposal: Proposal;
  reasoning: string;
  evidence: Evidence[]; // always non-empty; each item cites a real Signal
  confidence: number; // 0–1
  risk: RiskAssessment;
  status: DecisionStatus;
  human: HumanAction | null;
  outcome: DecisionOutcome | null;
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

export type EventType =
  // market
  | "market.tick"
  | "market.orderbook"
  | "market.ohlcv"
  // signals
  | "signal.created"
  | "signal.updated"
  // theses
  | "thesis.created"
  | "thesis.updated"
  | "thesis.invalidated"
  // decision lifecycle
  | "decision.proposed"
  | "decision.approved"
  | "decision.rejected"
  | "decision.expired"
  | "decision.executing"
  | "decision.executed"
  | "decision.failed"
  // orders
  | "order.submitted"
  | "order.filled"
  | "order.partially_filled"
  | "order.cancelled"
  | "order.failed"
  // portfolio
  | "portfolio.position_updated"
  | "portfolio.reconciled"
  | "portfolio.reconciliation_failed"
  // risk
  | "risk.limit_approached"
  | "risk.limit_breached"
  | "risk.halt"
  // system
  | "system.feed_healthy"
  | "system.feed_degraded"
  | "system.feed_dead"
  | "system.mode_changed"
  | "system.error";

export interface EventEnvelope<T = Record<string, unknown>> {
  id: string;
  event_type: EventType;
  source: string;
  schema_version: string;
  event_time: string; // ISO-8601 UTC
  ingest_time: string; // ISO-8601 UTC
  correlation_id: string | null; // threads all events for one Decision lifecycle
  payload: T;
}

export type AutonomyMode =
  | "observe"
  | "paper"
  | "assisted"
  | "semi_auto"
  | "supervised";
