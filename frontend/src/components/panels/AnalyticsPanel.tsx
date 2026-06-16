import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type { AnalyticsReport, EquityPoint } from "@/hooks/useAnalytics";

interface Props {
  report: AnalyticsReport | null;
}

function fmtRatio(v: number | null): string {
  return v === null ? "—" : v.toFixed(2);
}

function fmtPct(v: number | null): string {
  return v === null ? "—" : `${(v * 100).toFixed(1)}%`;
}

// Sharpe/Sortino: positive is good. Neutral until we have a real series.
function ratioColor(v: number | null): string {
  if (v === null) return "text-muted-foreground";
  return v > 0 ? "text-bullish" : v < 0 ? "text-bearish" : "text-muted-foreground";
}

function Metric({
  label,
  value,
  color,
  title,
}: {
  label: string;
  value: string;
  color?: string;
  title?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 rounded-sm bg-muted/60 p-2" title={title}>
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className={cn("font-mono text-sm font-semibold", color)}>{value}</span>
    </div>
  );
}

// Normalized SVG polyline of the equity curve. Flat series renders a mid line.
function Sparkline({ points }: { points: EquityPoint[] }) {
  const path = useMemo(() => {
    if (points.length < 2) return null;
    const ys = points.map((p) => parseFloat(p.equity));
    const min = Math.min(...ys);
    const max = Math.max(...ys);
    const span = max - min || 1;
    const W = 100;
    const H = 30;
    return ys
      .map((y, i) => {
        const x = (i / (ys.length - 1)) * W;
        const yy = H - ((y - min) / span) * H;
        return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${yy.toFixed(2)}`;
      })
      .join(" ");
  }, [points]);

  if (!path) {
    return (
      <p className="py-3 text-center text-[11px] text-muted-foreground">
        equity curve needs ≥2 days
      </p>
    );
  }

  const first = parseFloat(points[0].equity);
  const last = parseFloat(points[points.length - 1].equity);
  const up = last >= first;

  return (
    <svg
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      className="h-16 w-full"
      role="img"
      aria-label="Equity curve"
    >
      <path
        d={path}
        fill="none"
        strokeWidth={1.25}
        vectorEffect="non-scaling-stroke"
        className={up ? "stroke-bullish" : "stroke-bearish"}
      />
    </svg>
  );
}

export function AnalyticsPanel({ report }: Props) {
  if (!report) {
    return (
      <PanelShell title="ANALYTICS">
        <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
          loading analytics…
        </p>
      </PanelShell>
    );
  }

  const m = report.metrics;
  const netPnl = parseFloat(m.net_pnl);

  return (
    <PanelShell
      title="ANALYTICS"
      rightSlot={report.n_days > 0 ? `${report.n_days}D` : undefined}
    >
      <div className="space-y-3 p-3">
        <Sparkline points={report.equity_curve} />

        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          <Metric
            label="Sharpe"
            value={fmtRatio(m.sharpe)}
            color={ratioColor(m.sharpe)}
            title="Annualized Sharpe ratio. Net of fees, NOT slippage — informational, not a promotion gate."
          />
          <Metric
            label="Sortino"
            value={fmtRatio(m.sortino)}
            color={ratioColor(m.sortino)}
            title="Annualized Sortino ratio (downside-only dispersion)."
          />
          <Metric
            label="Volatility"
            value={fmtPct(m.volatility)}
            title="Annualized standard deviation of daily returns."
          />
          <Metric
            label="VaR 95%"
            value={fmtPct(m.var_95)}
            color={m.var_95 ? "text-bearish" : undefined}
            title="Historical 1-day Value-at-Risk at 95% confidence (loss fraction)."
          />
          <Metric
            label="Max DD"
            value={fmtPct(m.max_drawdown_pct)}
            color={m.max_drawdown_pct ? "text-bearish" : undefined}
            title={`Worst peak-to-trough on the equity curve: $${parseFloat(
              m.max_drawdown_value,
            ).toFixed(2)}`}
          />
          <Metric
            label="Net P&L"
            value={`${netPnl > 0 ? "+" : ""}$${netPnl.toFixed(2)}`}
            color={
              netPnl > 0
                ? "text-bullish"
                : netPnl < 0
                  ? "text-bearish"
                  : "text-muted-foreground"
            }
            title={`Realized P&L over ${m.trades} closed trade${m.trades !== 1 ? "s" : ""}.`}
          />
        </div>

        <p className="text-[10px] leading-relaxed text-muted-foreground/70">
          Sharpe/Sortino are net of fees but not slippage (paper book) —
          informational, not a promotion-gate criterion.
        </p>
      </div>
    </PanelShell>
  );
}
