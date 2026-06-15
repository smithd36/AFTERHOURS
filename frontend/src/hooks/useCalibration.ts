import { useCallback, useEffect, useRef, useState } from "react";
import type { EventEnvelope } from "@/types/core";

export interface CalibrationBucket {
  lo: number;
  hi: number;
  n: number;
  avg_confidence: number | null;
  hit_rate: number | null;
}

export interface CalibrationStats {
  n: number;
  ece: number | null;
  buckets: CalibrationBucket[];
}

export interface CalibrationReport {
  overall: CalibrationStats;
  by_mode: Record<string, CalibrationStats>;
}

export type GateGroup = "operational" | "calibration" | "economic";

export interface GateCriterion {
  name: string;
  required: string;
  current: string;
  passed: boolean;
  group: GateGroup;
}

export interface GateStatus {
  ready: boolean;
  criteria: GateCriterion[];
  deferred: string[];
}

export interface GatesReport {
  observe_to_paper: GateStatus;
  paper_to_assisted: GateStatus;
}

const REFRESH_DEBOUNCE_MS = 250;

/**
 * Server-side aggregates (ECE, gate readiness) fetched on mount and
 * refetched — debounced — whenever a decision.resolved or
 * risk.limit_breached event arrives on the stream.
 */
export function useCalibration(): {
  report: CalibrationReport | null;
  gates: GatesReport | null;
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [report, setReport] = useState<CalibrationReport | null>(null);
  const [gates, setGates] = useState<GatesReport | null>(null);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(() => {
    fetch("/api/calibration")
      .then((r) => r.json())
      .then((d: CalibrationReport) => setReport(d))
      .catch(() => {});
    fetch("/api/calibration/gates")
      .then((r) => r.json())
      .then((d: GatesReport) => setGates(d))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [refresh]);

  const handleEnvelope = useCallback(
    (envelope: EventEnvelope) => {
      if (
        envelope.event_type !== "decision.resolved" &&
        envelope.event_type !== "risk.limit_breached"
      ) {
        return;
      }
      if (timer.current !== null) return; // refresh already scheduled
      timer.current = window.setTimeout(() => {
        timer.current = null;
        refresh();
      }, REFRESH_DEBOUNCE_MS);
    },
    [refresh],
  );

  return { report, gates, handleEnvelope };
}
