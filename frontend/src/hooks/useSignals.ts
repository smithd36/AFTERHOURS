import { useCallback, useEffect, useLayoutEffect, useReducer, useRef } from "react";
import type { EventEnvelope } from "@/types/core";

export interface SignalRow {
  id: string;
  signalType: string;        // "price_alert" | "news" | ...
  instruments: string[];
  summary: string;           // title for news, summary text for price alerts
  sourceDomain: string;      // e.g. "coindesk.com" — empty for price alerts
  url: string;               // canonical link to source doc — empty if none
  eventTime: string;         // ISO-8601 — used for display age
  receivedAt: number;        // Date.now() — used for ordering
}

// Matches the backend /api/events/recent max limit — the panel scrolls, so the
// cap only bounds memory, not layout.
const MAX_SIGNALS = 500;
// High-volume families get a per-type cap so they can't crowd sparse alt-data
// (insider_tx/supply_chain/gov) out of the shared window — on a racing backfill
// or over a long live session. Caps sum well under MAX_SIGNALS, so the uncapped
// sparse types always have headroom. ponytail: tune the numbers if a family
// shows too few/many.
const TYPE_CAPS: Record<string, number> = { news: 400, price_alert: 50 };

interface SignalPayload {
  id: string;
  type: string;
  instruments: string[];
  provenance: { event_time: string; url?: string | null };
  payload: {
    summary?: string;
    title?: string;
    source_domain?: string;
  };
}

type Action =
  | { type: "add"; envelope: EventEnvelope }
  | { type: "refilter"; active: ReadonlySet<string> };

function toRow(envelope: EventEnvelope, receivedAt: number): SignalRow | null {
  const sp = envelope.payload as unknown as SignalPayload;
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
    url: sp.provenance?.url ?? "",
    eventTime: sp.provenance?.event_time ?? envelope.event_time,
    receivedAt,
  };
}

function isRelevant(row: SignalRow, active: ReadonlySet<string>): boolean {
  if (active.size === 0) return false;
  // General-market signals (no specific instruments) pass through when the
  // watchlist is non-empty — they provide macro context for watched assets.
  if (row.instruments.length === 0) return true;
  return row.instruments.some((i) => active.has(i));
}

function reducer(state: SignalRow[], action: Action): SignalRow[] {
  if (action.type === "add") {
    const row = toRow(action.envelope, Date.now());
    if (!row) return state;
    if (state.some((r) => r.id === row.id)) return state;
    let next = [row, ...state];
    // Drop the oldest rows of any capped family beyond its cap (next is
    // newest-first) so high-volume types can't bury sparse alt-data. O(n) per
    // capped type, n<=500 — cheap.
    for (const [type, cap] of Object.entries(TYPE_CAPS)) {
      const ofType = next.filter((r) => r.signalType === type);
      if (ofType.length > cap) {
        const drop = new Set(ofType.slice(cap).map((r) => r.id));
        next = next.filter((r) => !drop.has(r.id));
      }
    }
    return next.length > MAX_SIGNALS ? next.slice(0, MAX_SIGNALS) : next;
  }
  if (action.type === "refilter") {
    return state.filter((r) => isRelevant(r, action.active));
  }
  return state;
}

/**
 * activeInstruments: null while the watchlist is loading (no filter applied).
 * Once loaded, only signals for watched instruments (or general news) are shown;
 * existing signals for removed instruments are purged immediately.
 */
export function useSignals(activeInstruments: ReadonlySet<string> | null): {
  signals: SignalRow[];
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [signals, dispatch] = useReducer(reducer, []);

  // Keep a ref in sync so handleEnvelope always sees the latest value without
  // being recreated on every render.
  const activeRef = useRef(activeInstruments);
  useLayoutEffect(() => {
    activeRef.current = activeInstruments;
  });

  // When activeInstruments transitions from null→Set, or when the set changes
  // (instrument added/removed), refilter existing state.
  useEffect(() => {
    if (activeInstruments !== null) {
      dispatch({ type: "refilter", active: activeInstruments });
    }
  }, [activeInstruments]);

  const handleEnvelope = useCallback((envelope: EventEnvelope) => {
    if (envelope.event_type === "signal.created") {
      // Filter incoming signals against the current watchlist (if loaded).
      const active = activeRef.current;
      if (active !== null) {
        if (active.size === 0) return;
        const sp = envelope.payload as unknown as SignalPayload;
        const instruments = sp?.instruments ?? [];
        if (instruments.length > 0 && !instruments.some((i) => active.has(i))) {
          return;
        }
      }
      dispatch({ type: "add", envelope });
      return;
    }

    if (envelope.event_type === "watchlist.instrument_added") {
      const p = envelope.payload as Record<string, unknown>;
      const instrument = String(p.instrument ?? "");
      if (!instrument) return;
      // Backfill recent signals from the store for the newly watched instrument.
      fetch("/api/events/recent?types=signal.created&limit=500")
        .then((r) => r.json())
        .then((data: { events: EventEnvelope[] }) => {
          for (const ev of data.events ?? []) {
            const sp = ev.payload as unknown as SignalPayload;
            if ((sp?.instruments ?? []).includes(instrument)) {
              dispatch({ type: "add", envelope: ev });
            }
          }
        })
        .catch(() => {});
    }
  }, []);

  return { signals, handleEnvelope };
}
