import { useCallback, useEffect, useRef, useState } from "react";
import type { EventEnvelope } from "@/types/core";

export interface EquityPoint {
  day: string; // ISO date
  equity: string; // Decimal as string
}

export interface AnalyticsMetrics {
  sharpe: number | null;
  sortino: number | null;
  volatility: number | null;
  var_95: number | null;
  max_drawdown_value: string;
  max_drawdown_pct: number | null;
  net_pnl: string;
  trades: number;
}

export interface AnalyticsReport {
  equity_curve: EquityPoint[];
  metrics: AnalyticsMetrics;
  n_days: number;
}

const REFRESH_DEBOUNCE_MS = 400;

/**
 * Risk/return analytics (equity curve + Sharpe/Sortino/VaR) fetched on mount and
 * refetched — debounced — when an order.filled event arrives (a fill is what
 * moves the realized book; intra-hold tick marks aren't worth a refetch here).
 */
export function useAnalytics(): {
  report: AnalyticsReport | null;
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(() => {
    fetch("/api/analytics")
      .then((r) => r.json())
      .then((d: AnalyticsReport) => setReport(d))
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
      if (envelope.event_type !== "order.filled") return;
      if (timer.current !== null) return; // refresh already scheduled
      timer.current = window.setTimeout(() => {
        timer.current = null;
        refresh();
      }, REFRESH_DEBOUNCE_MS);
    },
    [refresh],
  );

  return { report, handleEnvelope };
}
