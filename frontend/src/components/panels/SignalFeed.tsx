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

type BadgeVariant = "price" | "news";

function typeBadge(signalType: string): { label: string; variant: BadgeVariant } {
  if (signalType === "price_alert") return { label: "PRICE", variant: "price" };
  return { label: "NEWS", variant: "news" };
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function SignalItem({ row }: { row: SignalRow }) {
  const { label, variant } = typeBadge(row.signalType);

  return (
    <div className="flex items-start gap-2 border-b border-border/40 px-3 py-2 hover:bg-muted/20 transition-colors duration-75">
      {/* Type badge */}
      <span
        className={cn(
          "mt-px shrink-0 rounded-sm px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
          variant === "price"
            ? "bg-warning/15 text-warning"
            : "bg-info/15 text-info",
        )}
      >
        {label}
      </span>

      {/* Content */}
      <div className="min-w-0 flex-1">
        {row.instruments.length > 0 && (
          <span className="mr-1.5 text-[10px] font-medium text-muted-foreground">
            {row.instruments.join(" · ")}
          </span>
        )}
        <span className="text-xs text-foreground leading-snug">{row.summary}</span>
        {row.sourceDomain && (
          <span className="ml-1.5 text-[10px] text-muted-foreground">
            {row.sourceDomain}
          </span>
        )}
      </div>

      {/* Age */}
      <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
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
        <p className="px-3 py-6 text-center text-xs text-muted-foreground">
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
