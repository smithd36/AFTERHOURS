import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import { TickerLink } from "@/components/TickerLink";
import type { ThesisRow } from "@/hooks/useTheses";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ageLabel(receivedAt: number): string {
  const diffS = Math.floor((Date.now() - receivedAt) / 1_000);
  if (diffS < 60) return `${diffS}s`;
  const diffM = Math.floor(diffS / 60);
  if (diffM < 60) return `${diffM}m`;
  const diffH = Math.floor(diffM / 60);
  if (diffH < 24) return `${diffH}h`;
  return `${Math.floor(diffH / 24)}d`;
}

type DirectionVariant = "long" | "short" | "neutral";

const DIRECTION_CLASSES: Record<DirectionVariant, string> = {
  long: "bg-bullish/15 text-bullish",
  short: "bg-bearish/15 text-bearish",
  neutral: "bg-muted/40 text-muted-foreground",
};

const STATUS_CLASSES: Record<ThesisRow["status"], string> = {
  active: "bg-info/15 text-info",
  expired: "bg-muted/40 text-muted-foreground",
  invalidated: "bg-bearish/15 text-bearish",
};

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function ThesisItem({ row }: { row: ThesisRow }) {
  const pct = Math.round(row.confidence * 100);

  return (
    <div
      className={cn(
        "border-b border-border/40 px-3 py-2.5 transition-colors duration-75 hover:bg-muted/20",
        row.status !== "active" && "opacity-50",
      )}
    >
      {/* Header row */}
      <div className="flex items-center gap-2 mb-1">
        <span
          className={cn(
            "shrink-0 rounded-sm px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            DIRECTION_CLASSES[row.direction],
          )}
        >
          {row.direction}
        </span>
        <span
          className={cn(
            "shrink-0 rounded-sm px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            STATUS_CLASSES[row.status],
          )}
        >
          {row.status}
        </span>
        <TickerLink
          symbol={row.instrument}
          className="text-[11px] font-medium text-muted-foreground"
        />
        <span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {pct}% conf · {ageLabel(row.receivedAt)}
        </span>
      </div>

      {/* Summary */}
      <p className="text-xs text-foreground leading-snug mb-1">{row.summary}</p>

      {/* Body — truncated to 2 lines via CSS */}
      {row.body && (
        <p className="text-[11px] text-muted-foreground leading-snug line-clamp-2 mb-1.5">
          {row.body}
        </p>
      )}

      {/* Invalidation conditions */}
      {row.invalidationConditions.length > 0 && (
        <ul className="space-y-0.5">
          {row.invalidationConditions.map((c, i) => (
            <li key={i} className="flex items-start gap-1 text-[11px] text-muted-foreground">
              <span className="mt-px text-warning shrink-0">↯</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

interface ThesisFeedProps {
  theses: ThesisRow[];
  collapsible?: boolean;
}

export function ThesisFeed({ theses, collapsible }: ThesisFeedProps) {
  const active = useMemo(() => theses.filter((t) => t.status === "active").length, [theses]);

  return (
    <PanelShell
      title="THESIS FEED"
      rightSlot={
        theses.length > 0
          ? `${active} ACTIVE · ${theses.length} TOTAL`
          : undefined
      }
      collapsible={collapsible}
    >
      {theses.length === 0 ? (
        <p className="px-3 py-6 text-center text-xs text-muted-foreground">
          awaiting theses…
        </p>
      ) : (
        <div className="max-h-[32rem] overflow-y-auto">
          {theses.map((row) => (
            <ThesisItem key={row.id} row={row} />
          ))}
        </div>
      )}
    </PanelShell>
  );
}
