import { useEffect, useRef } from "react";
import type { EventEnvelope } from "@/types/core";

// Signals are fetched separately at the backend's max limit so high-volume
// news doesn't crowd out (or get crowded out by) thesis/decision history.
const BACKFILL_REQUESTS = [
  { types: "signal.created", limit: 500 },
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

    for (const { types, limit } of BACKFILL_REQUESTS) {
      fetch(`/api/events/recent?types=${types}&limit=${limit}`)
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
