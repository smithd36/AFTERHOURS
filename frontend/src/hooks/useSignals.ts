import { useCallback, useReducer } from "react";
import type { EventEnvelope } from "@/types/core";

export interface SignalRow {
  id: string;
  signalType: string;        // "price_alert" | "news" | ...
  instruments: string[];
  summary: string;           // title for news, summary text for price alerts
  sourceDomain: string;      // e.g. "coindesk.com" — empty for price alerts
  eventTime: string;         // ISO-8601 — used for display age
  receivedAt: number;        // Date.now() — used for ordering
}

const MAX_SIGNALS = 50;

interface SignalPayload {
  id: string;
  type: string;
  instruments: string[];
  provenance: { event_time: string };
  payload: {
    summary?: string;
    title?: string;
    source_domain?: string;
  };
}

function toRow(envelope: EventEnvelope, receivedAt: number): SignalRow | null {
  const sp = envelope.payload as SignalPayload;
  if (!sp?.id || !sp?.type) return null;

  const p = sp.payload ?? {};
  const summary = p.title ?? p.summary ?? "";
  if (!summary) return null;

  return {
    id: sp.id,
    signalType: sp.type,
    instruments: sp.instruments ?? [],
    summary,
    sourceDomain: p.source_domain ?? "",
    eventTime: sp.provenance?.event_time ?? envelope.event_time,
    receivedAt,
  };
}

type State = SignalRow[];

function reducer(state: State, envelope: EventEnvelope): State {
  const row = toRow(envelope, Date.now());
  if (!row) return state;
  // Deduplicate by signal id
  if (state.some((r) => r.id === row.id)) return state;
  const next = [row, ...state];
  return next.length > MAX_SIGNALS ? next.slice(0, MAX_SIGNALS) : next;
}

export function useSignals(): {
  signals: SignalRow[];
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [signals, dispatch] = useReducer(reducer, []);

  const handleEnvelope = useCallback((envelope: EventEnvelope) => {
    if (envelope.event_type === "signal.created") {
      dispatch(envelope);
    }
  }, []);

  return { signals, handleEnvelope };
}
