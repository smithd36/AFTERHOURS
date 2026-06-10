import { useCallback, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type { WatchlistEntry } from "@/hooks/useWatchlist";

interface WatchlistPanelProps {
  entries: WatchlistEntry[];
  loading: boolean;
  ticks: Record<string, unknown>;
  onAdd: (instrument: string, market: "crypto" | "equity") => Promise<void>;
  onRemove: (instrument: string) => Promise<void>;
}

const MARKET_COLOR: Record<string, string> = {
  crypto: "text-blue-400",
  equity: "text-yellow-400",
};

function FeedDot({ live }: { live: boolean }) {
  return (
    <span
      title={live ? "live" : "waiting for feed"}
      className={cn(
        "inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full",
        live ? "bg-bullish" : "bg-muted-foreground/30",
      )}
    />
  );
}

function EntryRow({
  entry,
  live,
  onRemove,
}: {
  entry: WatchlistEntry;
  live: boolean;
  onRemove: (instrument: string) => void;
}) {
  return (
    <tr className="group border-b border-border/40 hover:bg-muted/20">
      <td className="w-4 px-3 py-1.5">
        <FeedDot live={live} />
      </td>
      <td className="py-1.5 pr-2 text-xs font-medium">{entry.instrument}</td>
      <td
        className={cn(
          "py-1.5 text-xs uppercase",
          MARKET_COLOR[entry.market] ?? "text-muted-foreground",
        )}
      >
        {entry.market}
      </td>
      <td className="px-3 py-1.5 text-right">
        <button
          onClick={() => onRemove(entry.instrument)}
          className="text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-bearish"
          title={`Remove ${entry.instrument}`}
        >
          ✕
        </button>
      </td>
    </tr>
  );
}

export function WatchlistPanel({
  entries,
  loading,
  ticks,
  onAdd,
  onRemove,
}: WatchlistPanelProps) {
  const [input, setInput] = useState("");
  const [market, setMarket] = useState<"crypto" | "equity">("crypto");
  const [submitting, setSubmitting] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = search.trim().toUpperCase();
    return q ? entries.filter((e) => e.instrument.includes(q)) : entries;
  }, [entries, search]);

  const handleRemove = useCallback(
    (instrument: string) => {
      onRemove(instrument).catch(() => {});
    },
    [onRemove],
  );

  const handleAdd = useCallback(async () => {
    const symbol = input.trim().toUpperCase();
    if (!symbol) return;
    setSubmitting(true);
    setAddError(null);
    try {
      await onAdd(symbol, market);
      setInput("");
      inputRef.current?.focus();
    } catch (e: unknown) {
      setAddError(String(e));
    } finally {
      setSubmitting(false);
    }
  }, [input, market, onAdd]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") handleAdd();
    },
    [handleAdd],
  );

  const countLabel = loading
    ? "loading…"
    : entries.length > 0
      ? `${entries.length} INSTRUMENT${entries.length !== 1 ? "S" : ""}`
      : undefined;

  return (
    <PanelShell title="WATCHLIST" rightSlot={countLabel}>
      {/* Add row */}
      <div className="flex items-center gap-1.5 border-b border-border/40 px-3 py-1.5">
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="BTC-USD, AAPL…"
          className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground/40"
          disabled={submitting}
        />
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value as "crypto" | "equity")}
          className="bg-transparent text-[10px] uppercase text-muted-foreground outline-none"
        >
          <option value="crypto">crypto</option>
          <option value="equity">equity</option>
        </select>
        <button
          onClick={handleAdd}
          disabled={submitting || !input.trim()}
          className="text-[10px] font-semibold uppercase tracking-wider text-bullish disabled:opacity-40 hover:text-bullish/80"
        >
          ADD
        </button>
      </div>

      {addError && (
        <p className="px-3 py-1 text-[10px] text-bearish">{addError}</p>
      )}

      {/* Search row — only shown when there's something to filter */}
      {entries.length > 3 && (
        <div className="border-b border-border/40 px-3 py-1">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="filter…"
            className="w-full bg-transparent text-[10px] outline-none placeholder:text-muted-foreground/30"
          />
        </div>
      )}

      {/* Entries */}
      {!loading && entries.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-muted-foreground">
          watchlist empty
        </p>
      ) : !loading && filtered.length === 0 ? (
        <p className="px-3 py-4 text-center text-[10px] text-muted-foreground">
          no match for "{search}"
        </p>
      ) : (
        <table className="w-full">
          <tbody>
            {filtered.map((entry) => (
              <EntryRow
                key={entry.instrument}
                entry={entry}
                live={entry.instrument in ticks}
                onRemove={handleRemove}
              />
            ))}
          </tbody>
        </table>
      )}
    </PanelShell>
  );
}
