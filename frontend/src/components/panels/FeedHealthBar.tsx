import { cn } from "@/lib/utils";
import type { FeedHealthRow } from "@/hooks/useFeedHealth";

// Friendly names; falls back to the raw feed_id for any feed not listed.
const LABEL: Record<string, string> = {
  news: "News",
  insider: "Insider",
  congress: "Congress",
  lobbying: "Lobbying",
  gov_contracts: "Contracts",
  supply_chain: "Supply",
};

/**
 * Slim always-visible strip of ingestion-feed health. A dead/disabled feed
 * shows amber with its failure cause on hover, so a silent outage (every
 * USASpending request failing, a missing token) is visible without reading
 * server logs.
 */
export function FeedHealthBar({ feeds }: { feeds: FeedHealthRow[] }) {
  if (feeds.length === 0) return null;
  const degraded = feeds.filter((f) => f.status === "degraded").length;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border/60 bg-card/40 px-3 py-1 text-[11px] sm:px-4">
      <span className="font-semibold uppercase tracking-widest text-muted-foreground/60">
        Feeds
      </span>
      {feeds.map((f) => (
        <span
          key={f.feedId}
          title={f.status === "degraded" ? f.detail || "degraded" : "healthy"}
          className={cn(
            "flex items-center gap-1.5",
            f.status === "degraded" ? "text-warning" : "text-muted-foreground/80",
          )}
        >
          <span
            className={cn(
              "inline-block h-1.5 w-1.5 rounded-full",
              f.status === "degraded" ? "bg-warning" : "bg-bullish",
            )}
          />
          {LABEL[f.feedId] ?? f.feedId}
        </span>
      ))}
      {degraded > 0 && (
        <span className="ml-auto font-medium text-warning">{degraded} degraded</span>
      )}
    </div>
  );
}
