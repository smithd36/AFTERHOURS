import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  LineSeries,
  type IChartApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { CandlestickChart, LineChart, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import { useChartNav } from "@/lib/chart-nav";
import { useChart, type Bar, type ChartRange } from "@/hooks/useChart";

const RANGES: ChartRange[] = ["1D", "1W", "1M", "3M", "1Y"];
const INTRADAY: ReadonlySet<ChartRange> = new Set<ChartRange>(["1D", "1W"]);

function fmtPrice(v: number): string {
  return v >= 100 ? v.toFixed(2) : v.toPrecision(4);
}

// Resolve a theme CSS var and normalize it to rgb/hex. The tokens are oklch(),
// which lightweight-charts' color parser can't read — a canvas fillStyle
// round-trip lets the browser convert oklch → sRGB for us.
function cssVar(name: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return raw;
  ctx.fillStyle = "#000";
  ctx.fillStyle = raw; // unparseable input leaves the previous value, so no throw
  return ctx.fillStyle;
}

interface Hover {
  price: number;
  time: number; // epoch seconds
}

/**
 * lightweight-charts canvas. Fills its parent (the parent owns the height, so the
 * same component serves the compact desktop panel and the full-height mobile tab).
 * Recreated when the data/series-kind changes (cheap; these are small). The
 * crosshair-move subscription reports the bar under the cursor up to the parent
 * for the Robinhood-style price-at-time readout (touch-drag scrubs on mobile).
 */
function ChartCanvas({
  bars,
  kind,
  intraday,
  onHover,
}: {
  bars: Bar[];
  kind: "candle" | "line";
  intraday: boolean;
  onHover: (h: Hover | null) => void;
}) {
  const elRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;

    const bullish = cssVar("--bullish");
    const bearish = cssVar("--bearish");
    const muted = cssVar("--muted-foreground");
    const border = cssVar("--border");

    const chart: IChartApi = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: muted,
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: border, visible: false },
        horzLines: { color: border },
      },
      rightPriceScale: { borderColor: border },
      timeScale: { borderColor: border, timeVisible: intraday, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });

    const up = bars[bars.length - 1].c >= bars[0].c;
    let read: (t: Time) => number | undefined;

    if (kind === "candle") {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: bullish,
        downColor: bearish,
        wickUpColor: bullish,
        wickDownColor: bearish,
        borderVisible: false,
      });
      series.setData(
        bars.map((b) => ({
          time: b.t as UTCTimestamp,
          open: b.o,
          high: b.h,
          low: b.l,
          close: b.c,
        })),
      );
      read = (t) => {
        const d = series.data().find((p) => p.time === t);
        return d && "close" in d ? d.close : undefined;
      };
    } else {
      const series = chart.addSeries(LineSeries, {
        color: up ? bullish : bearish,
        lineWidth: 2,
      });
      series.setData(bars.map((b) => ({ time: b.t as UTCTimestamp, value: b.c })));
      read = (t) => {
        const d = series.data().find((p) => p.time === t);
        return d && "value" in d ? d.value : undefined;
      };
    }

    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      if (param.time === undefined) {
        onHover(null);
        return;
      }
      const price = read(param.time);
      if (price === undefined) onHover(null);
      else onHover({ price, time: param.time as number });
    });

    return () => chart.remove();
  }, [bars, kind, intraday, onHover]);

  return <div ref={elRef} className="h-full w-full" />;
}

export function PriceChart({ fill = false }: { fill?: boolean }) {
  const { data, loading, error, load } = useChart();
  const { request } = useChartNav();
  const [query, setQuery] = useState("");
  const [range, setRange] = useState<ChartRange>("3M");
  const [kind, setKind] = useState<"candle" | "line">("candle");
  const [hover, setHover] = useState<Hover | null>(null);

  // A ticker clicked anywhere in the app (TickerLink → openChart) lands here as a
  // request; load it at the current range. `nonce` re-fires even for the same
  // symbol; `rangeRef` keeps it out of the deps so a range change doesn't reload.
  const rangeRef = useRef(range);
  rangeRef.current = range;
  useEffect(() => {
    if (!request?.symbol) return;
    setQuery(request.symbol);
    load(request.symbol, rangeRef.current);
  }, [request?.nonce, request?.symbol, load]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim()) load(query, range);
  };

  const pick = (r: ChartRange) => {
    setRange(r);
    if (data) load(data.instrument, r); // re-fetch the shown symbol at the new range
  };

  const bars = data?.bars ?? [];
  const last = bars.at(-1)?.c;
  const first = bars[0]?.c;
  const intraday = INTRADAY.has(range);

  // Cursor wins for the price; the % change is always measured vs the range start.
  const shownPrice = hover?.price ?? last;
  const change = shownPrice !== undefined && first !== undefined ? shownPrice - first : null;
  const changePct = change !== null && first ? (change / first) * 100 : null;
  const up = (change ?? 0) >= 0;

  const rightSlot = (
    <button
      type="button"
      onClick={() => setKind((k) => (k === "candle" ? "line" : "candle"))}
      title={`Switch to ${kind === "candle" ? "line" : "candlestick"} chart`}
      aria-label={`Switch to ${kind === "candle" ? "line" : "candlestick"} chart`}
      className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:h-9 pointer-coarse:w-9"
    >
      {kind === "candle" ? (
        <LineChart className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <CandlestickChart className="h-3.5 w-3.5" aria-hidden="true" />
      )}
    </button>
  );

  return (
    <PanelShell title="CHART" rightSlot={rightSlot} className={cn("flex flex-col", fill && "h-full")}>
      <div className={cn("flex flex-col gap-2 p-3", fill && "min-h-0 flex-1")}>
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search
              className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60"
              aria-hidden="true"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search symbol — AAPL or BTC-USD"
              aria-label="Search symbol"
              spellCheck={false}
              autoCapitalize="characters"
              className="w-full rounded border border-border bg-background py-1.5 pl-7 pr-2 font-mono text-base uppercase text-foreground placeholder:font-sans placeholder:normal-case placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:text-xs"
            />
          </div>
          {/* Full-width segmented control on mobile (even, tappable); natural width on ≥sm. */}
          <div className="flex shrink-0 overflow-hidden rounded border border-border">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => pick(r)}
                aria-pressed={range === r}
                className={cn(
                  "flex-1 px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider tabular-nums transition-colors sm:flex-none pointer-coarse:py-2.5",
                  range === r
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted/40",
                )}
              >
                {r}
              </button>
            ))}
          </div>
        </form>

        {data && shownPrice !== undefined && (
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-sm font-semibold text-foreground">
              {data.instrument}
            </span>
            <span className="font-mono text-sm tabular-nums text-foreground">
              {fmtPrice(shownPrice)}
            </span>
            {changePct !== null && (
              <span
                className={cn("font-mono text-xs tabular-nums", up ? "text-bullish" : "text-bearish")}
              >
                {up ? "+" : ""}
                {changePct.toFixed(2)}%
              </span>
            )}
            <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground/70">
              {hover
                ? new Date(hover.time * 1000).toLocaleString(undefined, {
                    month: "short",
                    day: "numeric",
                    ...(intraday ? { hour: "2-digit", minute: "2-digit" } : {}),
                  })
                : data.market}
            </span>
          </div>
        )}

        {/* One chart-area box for every state, so height stays stable across
            loading / error / empty / loaded. h-64 on desktop; fills the tab on mobile. */}
        <div className={cn("relative w-full", fill ? "min-h-0 flex-1" : "h-64")}>
          {error ? (
            <p className="absolute inset-0 grid place-items-center px-4 text-center text-[11px] text-bearish">
              {error}
            </p>
          ) : loading ? (
            <p className="absolute inset-0 grid place-items-center text-[11px] text-muted-foreground">
              loading bars…
            </p>
          ) : bars.length >= 2 ? (
            <ChartCanvas bars={bars} kind={kind} intraday={intraday} onHover={setHover} />
          ) : (
            <p className="absolute inset-0 grid place-items-center px-6 text-center text-[11px] text-muted-foreground">
              Search an equity or crypto symbol to chart its price history.
            </p>
          )}
        </div>
      </div>
    </PanelShell>
  );
}
