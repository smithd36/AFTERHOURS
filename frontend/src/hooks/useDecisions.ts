import { useCallback, useReducer } from "react";
import type { EventEnvelope } from "@/types/core";

export interface EvidenceItem {
  signal_id: string;
  summary: string;
  stance: "supporting" | "contradicting";
}

export interface DecisionRow {
  id: string;
  instrument: string;
  side: "long" | "short";
  sizeUsd: string;
  timeHorizon: string;
  reasoning: string;
  confidence: number;
  status: "proposed" | "approved" | "rejected";
  evidence: EvidenceItem[];
  rejectionReasons: string[];
  stopPrice: string | null;
  receivedAt: number;
}

const MAX_DECISIONS = 50;

type Action =
  | { type: "decision.proposed" | "decision.approved" | "decision.rejected"; envelope: EventEnvelope };

function toRow(envelope: EventEnvelope, status: DecisionRow["status"]): DecisionRow | null {
  const p = envelope.payload;
  if (!p.id) return null;
  const proposal = (p.proposal as Record<string, unknown>) ?? {};
  const risk = (p.risk as Record<string, unknown>) ?? {};
  return {
    id: String(p.id),
    instrument: String(proposal.instrument ?? ""),
    side: (proposal.side as "long" | "short") ?? "long",
    sizeUsd: String(proposal.size_usd ?? "0"),
    timeHorizon: String(proposal.time_horizon ?? ""),
    reasoning: String(p.reasoning ?? ""),
    confidence: Number(p.confidence ?? 0),
    status,
    evidence: (p.evidence as EvidenceItem[]) ?? [],
    rejectionReasons: (risk.rejection_reasons as string[]) ?? [],
    stopPrice: risk.stop_price ? String(risk.stop_price) : null,
    receivedAt: Date.now(),
  };
}

function reducer(state: DecisionRow[], action: Action): DecisionRow[] {
  const p = action.envelope.payload;
  const id = String(p.id ?? "");

  if (action.type === "decision.proposed") {
    if (!id || state.some((r) => r.id === id)) return state;
    const row = toRow(action.envelope, "proposed");
    if (!row) return state;
    const next = [row, ...state];
    return next.length > MAX_DECISIONS ? next.slice(0, MAX_DECISIONS) : next;
  }

  const statusMap = {
    "decision.approved": "approved" as const,
    "decision.rejected": "rejected" as const,
  };
  const newStatus = statusMap[action.type as keyof typeof statusMap];
  if (newStatus) {
    const exists = state.some((r) => r.id === id);
    if (exists) {
      return state.map((r) =>
        r.id === id
          ? {
              ...r,
              status: newStatus,
              sizeUsd: String((p.proposal as Record<string, unknown>)?.size_usd ?? r.sizeUsd),
              stopPrice:
                (p.risk as Record<string, unknown>)?.stop_price != null
                  ? String((p.risk as Record<string, unknown>).stop_price)
                  : r.stopPrice,
              rejectionReasons:
                ((p.risk as Record<string, unknown>)?.rejection_reasons as string[]) ??
                r.rejectionReasons,
            }
          : r,
      );
    }
    // received approved/rejected without a prior proposed (reconnect)
    const row = toRow(action.envelope, newStatus);
    if (!row) return state;
    const next = [row, ...state];
    return next.length > MAX_DECISIONS ? next.slice(0, MAX_DECISIONS) : next;
  }

  return state;
}

export function useDecisions(): {
  decisions: DecisionRow[];
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [decisions, dispatch] = useReducer(reducer, []);

  const handleEnvelope = useCallback((envelope: EventEnvelope) => {
    if (
      envelope.event_type === "decision.proposed" ||
      envelope.event_type === "decision.approved" ||
      envelope.event_type === "decision.rejected"
    ) {
      dispatch({ type: envelope.event_type as Action["type"], envelope });
    }
  }, []);

  return { decisions, handleEnvelope };
}
