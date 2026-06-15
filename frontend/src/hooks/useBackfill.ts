import { useEffect, useRef } from "react";
import type { EventEnvelope } from "@/types/core";

// Sparse alt-data subtypes that a high-volume feed can starve out of a shared
// signal window. Kept separate from price_alert (also high-volume) so neither
// price alerts nor news can bury them.
const ALT_SIGNAL_TYPES = [
  "insider_tx",
  "congressional_tx",
  "lobbying",
  "gov_contract",
  "supply_chain",
].join(",");

// Each signal family gets its own window so a high-volume type can't crowd the
// others out. price_alert is a low-value backlog — keep its window small so old
// alerts don't refill the feed on mount. ponytail: bump the 50 if you want more.
const BACKFILL_REQUESTS = [
  { types: "signal.created", limit: 500, signalTypes: "news" },
  { types: "signal.created", limit: 50, signalTypes: "price_alert" },
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
