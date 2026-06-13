import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type { PortfolioSnapshot } from "@/hooks/usePortfolio";

interface Props {
  snapshot: PortfolioSnapshot | null;
}

function PnlValue({ value }: { value: string }) {
  const n = parseFloat(value);
  const color = n > 0 ? "text-bullish" : n < 0 ? "text-bearish" : "text-muted-foreground";
  const prefix = n > 0 ? "+" : "";
  return (
    <span className={cn("font-mono", color)}>
      {prefix}${n.toFixed(2)}
    </span>
  );
}

export function PortfolioPanel({ snapshot }: Props) {
  const positions = useMemo(
    () => (snapshot ? Object.entries(snapshot.positions) : []),
    [snapshot],
  );

  if (!snapshot) {
    return (
      <PanelShell title="PORTFOLIO">
        <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">loading portfolio…</p>
      </PanelShell>
    );
  }

  return (
    <PanelShell title="PORTFOLIO">
      <div className="max-h-80 overflow-y-auto space-y-3 p-3">
        {/* Summary row */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-sm bg-muted/60 p-2 text-xs">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Cash</span>
            <span className="font-mono">${parseFloat(snapshot.cash).toFixed(2)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Total</span>
            <span className="font-mono">${parseFloat(snapshot.total_value).toFixed(2)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Unrealized P&L</span>
            <PnlValue value={snapshot.unrealized_pnl} />
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Day P&L</span>
            <PnlValue value={snapshot.daily_realized_pnl} />
          </div>
        </div>

        {/* Positions */}
        {positions.length === 0 ? (
          <p className="py-2 text-center text-[11px] text-muted-foreground">no open positions</p>
        ) : (
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Open positions ({positions.length})
            </p>
            {positions.map(([instrument, pos]) => (
              <div key={instrument} className="rounded-sm bg-muted/60 p-2 text-xs">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-semibold">{instrument}</span>
                    <span
                      className={cn(
                        "inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                        pos.side === "long"
                          ? "bg-bullish/20 text-bullish"
                          : "bg-bearish/20 text-bearish",
                      )}
                    >
                      {pos.side}
                    </span>
                  </div>
                  <PnlValue value={pos.unrealized_pnl} />
                </div>
                <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                  <span>
                    entry {parseFloat(pos.entry_price).toLocaleString()} → {parseFloat(pos.current_price).toLocaleString()}
                  </span>
                  {pos.stop_price && (
                    <span className="text-bearish">stop {parseFloat(pos.stop_price).toLocaleString()}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </PanelShell>
  );
}
