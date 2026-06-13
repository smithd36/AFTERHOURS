import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type { TickRow } from "@/hooks/useMarketTicks";

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function formatPrice(price: string): string {
  const n = parseFloat(price);
  if (isNaN(n)) return price;
  if (n >= 1_000)
    return n.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  if (n >= 1) return n.toFixed(4);
  return n.toFixed(6);
}

function formatPct(pct: string | null): string {
  if (pct === null) return "—";
  const n = parseFloat(pct);
  if (isNaN(n)) return pct;
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function pctColorClass(pct: string | null): string {
  if (pct === null) return "text-muted-foreground";
  const n = parseFloat(pct);
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

const HEADERS = ["INSTRUMENT", "PRICE", "24H %", "BID", "ASK"] as const;
const HIDE_BELOW_SM = new Set(["BID", "ASK"]);

function TickItem({ tick }: { tick: TickRow }) {
  const colorClass = pctColorClass(tick.priceChangePct24h);

  return (
    <tr className="border-b border-border/40 transition-colors duration-75 hover:bg-muted/20">
      <td className="px-3 py-1.5 text-xs font-medium">{tick.instrument}</td>
      <td className={cn("px-3 py-1.5 text-right text-xs tabular-nums", colorClass)}>
        {formatPrice(tick.price)}
      </td>
      <td className={cn("px-3 py-1.5 text-right text-xs tabular-nums", colorClass)}>
        {formatPct(tick.priceChangePct24h)}
      </td>
      <td className="hidden sm:table-cell px-3 py-1.5 text-right text-xs tabular-nums text-muted-foreground">
        {tick.bestBid ? formatPrice(tick.bestBid) : "—"}
      </td>
      <td className="hidden sm:table-cell px-3 py-1.5 text-right text-xs tabular-nums text-muted-foreground">
        {tick.bestAsk ? formatPrice(tick.bestAsk) : "—"}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

interface MarketWatchProps {
  ticks: Record<string, TickRow>;
}

export function MarketWatch({ ticks }: MarketWatchProps) {
  const rows = useMemo(
    () =>
      Object.values(ticks).sort((a, b) =>
        a.instrument.localeCompare(b.instrument),
      ),
    [ticks],
  );

  const countLabel =
    rows.length > 0
      ? `${rows.length} INSTRUMENT${rows.length !== 1 ? "S" : ""}`
      : undefined;

  return (
    <PanelShell title="MARKET WATCH" rightSlot={countLabel}>
      {rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
          awaiting data…
        </p>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="border-b border-border/40">
              {HEADERS.map((h) => (
                <th
                  key={h}
                  className={cn(
                    "px-3 py-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground",
                    h === "INSTRUMENT" ? "text-left" : "text-right",
                    HIDE_BELOW_SM.has(h) && "hidden sm:table-cell",
                  )}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((tick) => (
              <TickItem key={tick.instrument} tick={tick} />
            ))}
          </tbody>
        </table>
      )}
    </PanelShell>
  );
}
