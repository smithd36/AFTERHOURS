import { useCallback, useEffect, useLayoutEffect, useReducer, useRef } from "react";
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
  openedAt: string;  // decision event-clock (ISO) — the position's true age
}

const MAX_DECISIONS = 50;

type Action =
  | { type: "decision.proposed" | "decision.approved" | "decision.rejected"; envelope: EventEnvelope }
  | { type: "refilter"; active: ReadonlySet<string> };

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
    openedAt: String(envelope.event_time ?? ""),
  };
}

function reducer(state: DecisionRow[], action: Action): DecisionRow[] {
  if (action.type === "refilter") {
    return state.filter((r) => !r.instrument || action.active.has(r.instrument));
  }

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
    const row = toRow(action.envelope, newStatus);
    if (!row) return state;
    const next = [row, ...state];
    return next.length > MAX_DECISIONS ? next.slice(0, MAX_DECISIONS) : next;
  }

  return state;
}

export function useDecisions(activeInstruments: ReadonlySet<string> | null): {
  decisions: DecisionRow[];
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [decisions, dispatch] = useReducer(reducer, []);

  const activeRef = useRef(activeInstruments);
  useLayoutEffect(() => {
    activeRef.current = activeInstruments;
  });

  useEffect(() => {
    if (activeInstruments !== null) {
      dispatch({ type: "refilter", active: activeInstruments });
    }
  }, [activeInstruments]);

  const handleEnvelope = useCallback((envelope: EventEnvelope) => {
    const et = envelope.event_type;

    if (
      et === "decision.proposed" ||
      et === "decision.approved" ||
      et === "decision.rejected"
    ) {
      const active = activeRef.current;
      if (active !== null) {
        const proposal = (envelope.payload.proposal as Record<string, unknown>) ?? {};
        const instrument = String(proposal.instrument ?? "");
        if (instrument && !active.has(instrument)) return;
      }
      dispatch({ type: et, envelope });
      return;
    }

    if (et === "watchlist.instrument_added") {
      const p = envelope.payload as Record<string, unknown>;
      const instrument = String(p.instrument ?? "");
      if (!instrument) return;
      fetch(
        "/api/events/recent?types=decision.proposed,decision.approved,decision.rejected&limit=200",
      )
        .then((r) => r.json())
        .then((data: { events: EventEnvelope[] }) => {
          for (const ev of data.events ?? []) {
            const proposal = (ev.payload.proposal as Record<string, unknown>) ?? {};
            if (String(proposal.instrument ?? "") !== instrument) continue;
            const t = ev.event_type as Action["type"];
            if (
              t === "decision.proposed" ||
              t === "decision.approved" ||
              t === "decision.rejected"
            ) {
              dispatch({ type: t, envelope: ev });
            }
          }
        })
        .catch(() => {});
    }
  }, []);

  return { decisions, handleEnvelope };
}
