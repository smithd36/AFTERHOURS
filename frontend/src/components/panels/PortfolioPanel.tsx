import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type { PortfolioSnapshot, PositionSnapshot, TradeRecord } from "@/hooks/usePortfolio";
import type { DecisionRow, EvidenceItem } from "@/hooks/useDecisions";
import type { EventEnvelope } from "@/types/core";

interface Props {
  snapshot: PortfolioSnapshot | null;
  decisions: DecisionRow[];
}

// The fields the drill-down shows — sourced from the live decision buffer or,
// after a restart wipes it, lazily fetched from /api/events.
interface DecisionDetail {
  reasoning: string;
  confidence: number;
  evidence: EvidenceItem[];
  openedAt: string;
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

// "3h 12m" / "4m" / "" — the position's age, the staleness signal.
function ageLabel(openedAt: string): string {
  const t = Date.parse(openedAt);
  if (Number.isNaN(t)) return "";
  const mins = Math.max(0, Math.floor((Date.now() - t) / 60_000));
  if (mins < 60) return `${mins}m`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

function detailFromRow(d: DecisionRow): DecisionDetail {
  return {
    reasoning: d.reasoning,
    confidence: d.confidence,
    evidence: d.evidence,
    openedAt: d.openedAt,
  };
}

function detailFromEnvelope(ev: EventEnvelope): DecisionDetail {
  const p = ev.payload;
  return {
    reasoning: String(p.reasoning ?? ""),
    confidence: Number(p.confidence ?? 0),
    evidence: (p.evidence as EvidenceItem[]) ?? [],
    openedAt: String(ev.event_time ?? ""),
  };
}

function DecisionDetailView({ detail }: { detail: DecisionDetail }) {
  return (
    <div className="mt-2 space-y-1.5 border-t border-border/60 pt-2 text-[11px]">
      <p className="text-muted-foreground">{detail.reasoning || "no reasoning recorded"}</p>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-muted-foreground">
        <span>{Math.round(detail.confidence * 100)}% confidence</span>
        {detail.openedAt && (
          <span>
            opened {new Date(detail.openedAt).toLocaleString()} ({ageLabel(detail.openedAt)} ago)
          </span>
        )}
      </div>
      {detail.evidence.length > 0 && (
        <div className="space-y-0.5">
          {detail.evidence.map((e, i) => (
            <p
              key={`${e.signal_id}-${i}`}
              className={e.stance === "contradicting" ? "text-bearish" : "text-muted-foreground"}
            >
              {e.stance === "contradicting" ? "✗" : "✓"} {e.summary}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function PositionCard({
  instrument,
  pos,
  buffered,
}: {
  instrument: string;
  pos: PositionSnapshot;
  buffered: DecisionRow | undefined;
}) {
  const [open, setOpen] = useState(false);
  // null = not yet fetched, undefined = fetched-but-not-found
  const [fetched, setFetched] = useState<DecisionDetail | null | undefined>(null);
  const [loading, setLoading] = useState(false);

  const detail = buffered ? detailFromRow(buffered) : fetched ?? undefined;

  function toggle() {
    const next = !open;
    setOpen(next);
    // Lazily pull from the event store only when the buffer misses (post-restart).
    if (next && !buffered && fetched === null && !loading) {
      setLoading(true);
      fetch(
        "/api/events/recent?types=decision.proposed,decision.approved,decision.rejected&limit=200",
      )
        .then((r) => r.json())
        .then((data: { events: EventEnvelope[] }) => {
          const match = (data.events ?? []).find(
            (ev) => String(ev.payload.id ?? "") === pos.decision_id,
          );
          setFetched(match ? detailFromEnvelope(match) : undefined);
        })
        .catch(() => setFetched(undefined))
        .finally(() => setLoading(false));
    }
  }

  return (
    <div className="rounded-sm bg-muted/60 p-2 text-xs">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="w-full text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">{open ? "▾" : "▸"}</span>
            <span className="font-mono font-semibold">{instrument}</span>
            <span
              className={cn(
                "inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                pos.side === "long" ? "bg-bullish/20 text-bullish" : "bg-bearish/20 text-bearish",
              )}
            >
              {pos.side}
            </span>
          </div>
          <PnlValue value={pos.unrealized_pnl} />
        </div>
        <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
          <span>
            entry {parseFloat(pos.entry_price).toLocaleString()} →{" "}
            {parseFloat(pos.current_price).toLocaleString()}
          </span>
          {pos.stop_price && (
            <span className="text-bearish">stop {parseFloat(pos.stop_price).toLocaleString()}</span>
          )}
        </div>
      </button>

      {open &&
        (detail ? (
          <DecisionDetailView detail={detail} />
        ) : (
          <p className="mt-2 border-t border-border/60 pt-2 text-[11px] text-muted-foreground">
            {loading
              ? "fetching decision…"
              : "decision not in recent history (buffer cleared and no match in /api/events)"}
          </p>
        ))}
    </div>
  );
}

function ClosedTrades({ trades }: { trades: TradeRecord[] }) {
  const closed = useMemo(() => trades.filter((t) => t.action === "close"), [trades]);
  if (closed.length === 0) {
    return (
      <p className="py-2 text-center text-[11px] text-muted-foreground">no closed trades today</p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Closed trades ({closed.length})
      </p>
      <div className="rounded-sm bg-muted/60 p-2 space-y-0.5">
        {closed.map((t, i) => (
          <TradeRow key={`${t.decision_id}-${t.action}-${i}`} trade={t} />
        ))}
      </div>
    </div>
  );
}

function TradeRow({ trade }: { trade: TradeRecord }) {
  // 24h clock avoids AM/PM ambiguity; fills can happen outside equity hours (crypto, paper)
  const time = new Date(trade.ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const isClose = trade.action === "close";
  const exitPrice = parseFloat(trade.fill_price).toLocaleString();
  const entryPrice = trade.entry_price ? parseFloat(trade.entry_price).toLocaleString() : null;

  return (
    <div className="flex items-center gap-1.5 py-0.5 text-[11px] font-mono">
      <span className="w-11 shrink-0 text-muted-foreground">{time}</span>
      <span className="w-14 shrink-0 font-semibold">{trade.instrument}</span>

      {/* Action badge */}
      <span className={cn(
        "shrink-0 rounded px-1 py-0.5 text-[10px] font-bold uppercase tracking-wider",
        isClose ? "bg-muted text-muted-foreground" : "bg-primary/15 text-primary",
      )}>
        {isClose ? "CLOSE" : "OPEN"}
      </span>

      {/* Side badge — always shown */}
      <span className={cn(
        "shrink-0 rounded px-1 py-0.5 text-[10px] font-bold uppercase tracking-wider",
        trade.side === "long" ? "bg-bullish/20 text-bullish" : "bg-bearish/20 text-bearish",
      )}>
        {trade.side}
      </span>

      {/* Price info */}
      <span className="min-w-0 flex-1 truncate text-right text-muted-foreground">
        {isClose && entryPrice
          ? <>{entryPrice} → {exitPrice}</>
          : <>@{exitPrice}</>}
      </span>

      {/* Right-most: P&L for closes, notional for opens */}
      {isClose && trade.realized_pnl !== null ? (
        <PnlValue value={trade.realized_pnl} />
      ) : (
        <span className="shrink-0 text-muted-foreground">
          ${parseFloat(trade.cost_usd).toFixed(2)}
        </span>
      )}
    </div>
  );
}

export function PortfolioPanel({ snapshot, decisions }: Props) {
  const positions = useMemo(
    () => (snapshot ? Object.entries(snapshot.positions) : []),
    [snapshot],
  );
  const byId = useMemo(() => {
    const m = new Map<string, DecisionRow>();
    for (const d of decisions) m.set(d.id, d);
    return m;
  }, [decisions]);

  if (!snapshot) {
    return (
      <PanelShell title="PORTFOLIO">
        <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">loading portfolio…</p>
      </PanelShell>
    );
  }

  return (
    <PanelShell title="PORTFOLIO" className="flex flex-col">
      {/* flex-1 fills the grid cell (which stretches to the taller sibling) so the
          panel extends full-length instead of cutting off at a fixed cap. The
          page (main) owns the scroll, so this only scrolls if content overflows. */}
      <div className="flex-1 min-h-0 space-y-3 overflow-y-auto p-3">
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
              <PositionCard
                key={instrument}
                instrument={instrument}
                pos={pos}
                buffered={byId.get(pos.decision_id)}
              />
            ))}
          </div>
        )}

        {/* Closed trades */}
        <ClosedTrades trades={snapshot.trades} />
      </div>
    </PanelShell>
  );
}
