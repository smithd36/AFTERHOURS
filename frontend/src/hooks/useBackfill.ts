import { useEffect, useRef } from "react";
import type { EventEnvelope } from "@/types/core";

// Sparse alt-data subtypes that the high-volume news feed can starve out of a
// shared signal window. Fetched in their own request (filtered by payload type)
// so each gets a fair slice of the backfill.
const ALT_SIGNAL_TYPES = [
  "price_alert",
  "insider_tx",
  "congressional_tx",
  "lobbying",
  "gov_contract",
  "supply_chain",
].join(",");

// Signals are fetched separately at the backend's max limit so high-volume
// news doesn't crowd out (or get crowded out by) thesis/decision history.
const BACKFILL_REQUESTS = [
  { types: "signal.created", limit: 500 },
  // Same event type, but only the sparse subtypes — own window so news can't bury them.
  { types: "signal.created", limit: 500, signalTypes: ALT_SIGNAL_TYPES },
  {
    types: [
      "thesis.created",
      "thesis.invalidated",
      "decision.proposed",
      "decision.approved",
      "decision.rejected",
    ].join(","),
    limit: 200,
  },
  // Feed health: sparse, own request so it can't be crowded out by news.
  { types: ["system.feed_healthy", "system.feed_degraded"].join(","), limit: 50 },
];

/**
 * Hydrates panel state on mount by replaying recent events from the
 * gateway's audit log through the same handler used for live WS events.
 * Events arrive oldest-first, so reducers end up in newest-first order
 * and live events that race the fetch are deduplicated by id.
 */
export function useBackfill(onEnvelope: (envelope: EventEnvelope) => void): void {
  const onEnvelopeRef = useRef(onEnvelope);
  onEnvelopeRef.current = onEnvelope;

  useEffect(() => {
    let cancelled = false;

    for (const req of BACKFILL_REQUESTS) {
      const signalTypes = "signalTypes" in req ? `&signal_types=${req.signalTypes}` : "";
      fetch(`/api/events/recent?types=${req.types}&limit=${req.limit}${signalTypes}`)
        .then((r) => r.json())
        .then((data: { events: EventEnvelope[] }) => {
          if (cancelled) return;
          for (const envelope of data.events ?? []) {
            onEnvelopeRef.current(envelope);
          }
        })
        .catch(() => {
          // backfill is best-effort — live stream still populates panels
        });
    }

    return () => {
      cancelled = true;
    };
  }, []);
}
