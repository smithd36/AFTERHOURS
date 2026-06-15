import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type { SignalRow } from "@/hooks/useSignals";

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
}

export function SignalFeed({ signals }: SignalFeedProps) {
  return (
    <PanelShell
      title="SIGNAL FEED"
      rightSlot={signals.length > 0 ? `${signals.length} SIGNAL${signals.length !== 1 ? "S" : ""}` : undefined}
    >
      {signals.length === 0 ? (
        <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
          awaiting signals…
        </p>
      ) : (
        <div className="max-h-96 overflow-y-auto">
          {signals.map((row) => (
            <SignalItem key={row.id} row={row} />
          ))}
        </div>
      )}
    </PanelShell>
  );
}
