import { useCallback, useEffect, useLayoutEffect, useReducer, useRef } from "react";
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
  | { type: "thesis.invalidated"; thesisId: string; reason: string }
  | { type: "refilter"; active: ReadonlySet<string> };

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
  if (action.type === "refilter") {
    return state.filter((r) => action.active.has(r.instrument));
  }
  return state;
}

export function useTheses(activeInstruments: ReadonlySet<string> | null): {
  theses: ThesisRow[];
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [theses, dispatch] = useReducer(reducer, []);

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
    if (envelope.event_type === "thesis.created") {
      const active = activeRef.current;
      if (active !== null) {
        const instrument = String(envelope.payload.instrument ?? "");
        if (instrument && !active.has(instrument)) return;
      }
      dispatch({ type: "thesis.created", envelope });
      return;
    }

    if (envelope.event_type === "thesis.invalidated") {
      const p = envelope.payload;
      dispatch({
        type: "thesis.invalidated",
        thesisId: String(p.thesis_id ?? ""),
        reason: String(p.reason ?? ""),
      });
      return;
    }

    if (envelope.event_type === "watchlist.instrument_added") {
      const p = envelope.payload as Record<string, unknown>;
      const instrument = String(p.instrument ?? "");
      if (!instrument) return;
      fetch("/api/events/recent?types=thesis.created,thesis.invalidated&limit=200")
        .then((r) => r.json())
        .then((data: { events: EventEnvelope[] }) => {
          for (const ev of data.events ?? []) {
            if (ev.event_type === "thesis.created") {
              if (String(ev.payload.instrument ?? "") === instrument) {
                dispatch({ type: "thesis.created", envelope: ev });
              }
            } else if (ev.event_type === "thesis.invalidated") {
              dispatch({
                type: "thesis.invalidated",
                thesisId: String(ev.payload.thesis_id ?? ""),
                reason: String(ev.payload.reason ?? ""),
              });
            }
          }
        })
        .catch(() => {});
    }
  }, []);

  return { theses, handleEnvelope };
}
