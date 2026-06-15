import { useCallback, useReducer } from "react";
import type { EventEnvelope } from "@/types/core";

export type FeedStatus = "healthy" | "degraded";

export interface FeedHealthRow {
  feedId: string;
  status: FeedStatus;
  detail: string; // failure cause when degraded (shown on hover)
  ts: number;
}

interface HealthPayload {
  feed_id?: string;
  detail?: string;
}

function statusFor(eventType: string): FeedStatus | null {
  if (eventType === "system.feed_healthy") return "healthy";
  if (eventType === "system.feed_degraded") return "degraded";
  return null;
}

type State = Record<string, FeedHealthRow>;

function reducer(state: State, envelope: EventEnvelope): State {
  const status = statusFor(envelope.event_type);
  if (!status) return state; // not a health event → no re-render
  const p = envelope.payload as unknown as HealthPayload;
  if (!p.feed_id) return state;
  return {
    ...state,
    [p.feed_id]: { feedId: p.feed_id, status, detail: p.detail ?? "", ts: Date.now() },
  };
}

/**
 * Reduces system.feed_healthy / system.feed_degraded events into the latest
 * status per feed. Feeds announce themselves on their first poll outcome and
 * only re-emit on a status flip, so this map is small and updates rarely.
 */
export function useFeedHealth(): {
  feeds: FeedHealthRow[];
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [state, dispatch] = useReducer(reducer, {});
  const handleEnvelope = useCallback((envelope: EventEnvelope) => dispatch(envelope), []);
  const feeds = Object.values(state).sort((a, b) => a.feedId.localeCompare(b.feedId));
  return { feeds, handleEnvelope };
}
