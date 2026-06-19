import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { useChartNav } from "@/lib/chart-nav";

/**
 * Any equity/crypto symbol, rendered as a control that opens the Discover price
 * chart for that symbol. Inherits its type styling from the caller via
 * `className` so it blends into dense rows; it adds only a hover/focus
 * affordance. `stopPropagation` keeps it from also triggering an enclosing row's
 * click or expand handler.
 */
export function TickerLink({
  symbol,
  className,
  children,
}: {
  symbol: string;
  className?: string;
  children?: ReactNode;
}) {
  const { openChart } = useChartNav();
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        openChart(symbol);
      }}
      title={`Chart ${symbol}`}
      aria-label={`View ${symbol} price chart`}
      className={cn(
        "cursor-pointer rounded-sm underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
    >
      {children ?? symbol}
    </button>
  );
}
