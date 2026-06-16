import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type { SignalRow } from "@/hooks/useSignals";

// ---------------------------------------------------------------------------
// Tabs — the flat feed is grouped by signal type so a high-volume family (news)
// can't visually bury a sparse one (insider/supply). The bar is built from the
// types actually present; this is just the preferred order — unlisted types are
// appended after these. Labels come from SOURCE_BADGE below.
// ---------------------------------------------------------------------------

const TAB_ORDER = [
  "news",
  "price_alert",
  "insider_tx",
  "congressional_tx",
  "gov_contract",
  "lobbying",
  "supply_chain",
];

function tabRank(type: string): number {
  const i = TAB_ORDER.indexOf(type);
  return i === -1 ? TAB_ORDER.length : i;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ageLabel(eventTime: string): string {
  const diffMs = Date.now() - new Date(eventTime).getTime();
  const diffS = Math.floor(diffMs / 1_000);
  if (diffS < 60) return `${diffS}s`;
  const diffM = Math.floor(diffS / 60);
  if (diffM < 60) return `${diffM}m`;
  const diffH = Math.floor(diffM / 60);
  if (diffH < 24) return `${diffH}h`;
  return `${Math.floor(diffH / 24)}d`;
}

// Source badge: the label names the feed; colour groups by factor family — the
// three government_exposure sources (congress/contract/lobby) share one hue per
// ADR-010. Unknown types fall back to a neutral SIGNAL badge rather than being
// mislabelled NEWS.
const SOURCE_BADGE: Record<string, { label: string; className: string }> = {
  price_alert: { label: "PRICE", className: "bg-warning/15 text-warning" },
  news: { label: "NEWS", className: "bg-info/15 text-info" },
  insider_tx: { label: "INSIDER", className: "bg-bullish/15 text-bullish" },
  congressional_tx: { label: "CONGRESS", className: "bg-bearish/15 text-bearish" },
  gov_contract: { label: "CONTRACT", className: "bg-bearish/15 text-bearish" },
  lobbying: { label: "LOBBY", className: "bg-bearish/15 text-bearish" },
  supply_chain: { label: "SUPPLY", className: "bg-muted text-muted-foreground" },
};
const DEFAULT_BADGE = { label: "SIGNAL", className: "bg-muted text-muted-foreground" };

function sourceBadge(signalType: string): { label: string; className: string } {
  return SOURCE_BADGE[signalType] ?? DEFAULT_BADGE;
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function SignalItem({ row }: { row: SignalRow }) {
  const { label, className } = sourceBadge(row.signalType);

  return (
    <div className="flex items-start gap-2 border-b border-border/40 px-3 py-2 hover:bg-muted/20 transition-colors duration-75">
      {/* Source badge */}
      <span
        className={cn(
          "mt-px shrink-0 rounded-sm px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
          className,
        )}
      >
        {label}
      </span>

      {/* Content */}
      <div className="min-w-0 flex-1">
        {row.instruments.length > 0 && (
          <span className="mr-1.5 text-[11px] font-medium text-muted-foreground">
            {row.instruments.join(" · ")}
          </span>
        )}
        {row.url ? (
          <a
            href={row.url}
            target="_blank"
            rel="noopener noreferrer"
            title="Open source document"
            className="text-xs text-foreground leading-snug hover:text-info hover:underline"
          >
            {row.summary}
          </a>
        ) : (
          <span className="text-xs text-foreground leading-snug">{row.summary}</span>
        )}
        {row.sourceDomain && (
          <span className="ml-1.5 text-[11px] text-muted-foreground">
            {row.sourceDomain}
          </span>
        )}
      </div>

      {/* Age */}
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
        {ageLabel(row.eventTime)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

interface SignalFeedProps {
  signals: SignalRow[];
  collapsible?: boolean;
}

export function SignalFeed({ signals, collapsible }: SignalFeedProps) {
  const [active, setActive] = useState<string>("all");

  // Tab list + per-type counts, derived from the signals present. The active
  // tab is kept visible even if it momentarily drops to zero, so the selection
  // never disappears under the user.
  const { tabs, counts } = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const s of signals) counts[s.signalType] = (counts[s.signalType] ?? 0) + 1;
    const present = new Set(Object.keys(counts));
    if (active !== "all") present.add(active);
    const ordered = [...present].sort((a, b) => tabRank(a) - tabRank(b));
    return { tabs: ["all", ...ordered], counts };
  }, [signals, active]);

  const visible = useMemo(
    () => (active === "all" ? signals : signals.filter((s) => s.signalType === active)),
    [signals, active],
  );

  return (
    <PanelShell
      title="SIGNAL FEED"
      rightSlot={signals.length > 0 ? `${signals.length} SIGNAL${signals.length !== 1 ? "S" : ""}` : undefined}
      collapsible={collapsible}
    >
      {/* Family tabs */}
      <div
        role="tablist"
        aria-label="Signal families"
        className="flex flex-wrap gap-1 border-b border-border/60 px-2 py-1.5"
      >
        {tabs.map((key) => {
          const label = key === "all" ? "ALL" : sourceBadge(key).label;
          const count = key === "all" ? signals.length : counts[key] ?? 0;
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={active === key}
              onClick={() => setActive(key)}
              className={cn(
                "rounded-sm px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                active === key
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
              )}
            >
              {label}
              <span className="ml-1 tabular-nums opacity-60">{count}</span>
            </button>
          );
        })}
      </div>

      {visible.length === 0 ? (
        <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
          {signals.length === 0 ? "awaiting signals…" : "no signals in this family"}
        </p>
      ) : (
        <div className="max-h-96 overflow-y-auto">
          {visible.map((row) => (
            <SignalItem key={row.id} row={row} />
          ))}
        </div>
      )}
    </PanelShell>
  );
}
