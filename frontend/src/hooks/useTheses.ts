import { useCallback, useReducer } from "react";
import type { EventEnvelope } from "@/types/core";

export interface ThesisRow {
  id: string;
  instrument: string;
  summary: string;
  body: string;
  direction: "long" | "short" | "neutral";
  confidence: number;
  invalidationConditions: string[];
  timeHorizonHours: number;
  status: "active" | "invalidated" | "expired";
  receivedAt: number;
}

const MAX_THESES = 20;

type Action =
  | { type: "thesis.created"; envelope: EventEnvelope }
  | { type: "thesis.invalidated"; thesisId: string; reason: string };

function toRow(envelope: EventEnvelope): ThesisRow | null {
  const p = envelope.payload;
  if (!p.id || !p.instrument) return null;
  return {
    id: String(p.id),
    instrument: String(p.instrument),
    summary: String(p.summary ?? ""),
    body: String(p.body ?? ""),
    direction: (p.direction as ThesisRow["direction"]) ?? "neutral",
    confidence: Number(p.confidence ?? 0),
    invalidationConditions: (p.invalidation_conditions as string[]) ?? [],
    timeHorizonHours: Number(p.time_horizon_hours ?? 8),
    status: "active",
    receivedAt: Date.now(),
  };
}

function reducer(state: ThesisRow[], action: Action): ThesisRow[] {
  if (action.type === "thesis.created") {
    const row = toRow(action.envelope);
    if (!row) return state;
    if (state.some((r) => r.id === row.id)) return state;
    const next = [row, ...state];
    return next.length > MAX_THESES ? next.slice(0, MAX_THESES) : next;
  }
  if (action.type === "thesis.invalidated") {
    return state.map((r) =>
      r.id === action.thesisId
        ? { ...r, status: action.reason === "expired" ? "expired" : "invalidated" }
        : r,
    );
  }
  return state;
}

export function useTheses(): {
  theses: ThesisRow[];
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [theses, dispatch] = useReducer(reducer, []);

  const handleEnvelope = useCallback((envelope: EventEnvelope) => {
    if (envelope.event_type === "thesis.created") {
      dispatch({ type: "thesis.created", envelope });
    } else if (envelope.event_type === "thesis.invalidated") {
      const p = envelope.payload;
      dispatch({
        type: "thesis.invalidated",
        thesisId: String(p.thesis_id ?? ""),
        reason: String(p.reason ?? ""),
      });
    }
  }, []);

  return { theses, handleEnvelope };
}
