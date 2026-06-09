import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type { DecisionRow } from "@/hooks/useDecisions";

interface Props {
  decisions: DecisionRow[];
  mode: string;
  onExecute?: (id: string) => void;
  onReject?: (id: string) => void;
}

function StatusBadge({ status }: { status: DecisionRow["status"] }) {
  const styles: Record<DecisionRow["status"], string> = {
    proposed: "bg-muted text-muted-foreground",
    approved: "bg-bullish/20 text-bullish",
    rejected: "bg-bearish/20 text-bearish",
  };
  return (
    <span
      className={cn(
        "inline-block rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
        styles[status],
      )}
    >
      {status}
    </span>
  );
}

function SideBadge({ side }: { side: "long" | "short" }) {
  return (
    <span
      className={cn(
        "inline-block rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider",
        side === "long" ? "bg-bullish/20 text-bullish" : "bg-bearish/20 text-bearish",
      )}
    >
      {side}
    </span>
  );
}

function DecisionCard({
  decision,
  mode,
  onExecute,
  onReject,
}: {
  decision: DecisionRow;
  mode: string;
  onExecute?: (id: string) => void;
  onReject?: (id: string) => void;
}) {
  const canAct = mode === "assisted" && decision.status === "approved";
  const pnlColor =
    parseFloat(decision.sizeUsd) > 0 ? "text-foreground" : "text-muted-foreground";

  return (
    <div className="rounded border border-border p-3 text-xs space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold">{decision.instrument}</span>
          <SideBadge side={decision.side} />
          <StatusBadge status={decision.status} />
        </div>
        <span className={cn("font-mono text-[11px]", pnlColor)}>
          ${parseFloat(decision.sizeUsd).toFixed(2)}
        </span>
      </div>

      <p className="text-muted-foreground line-clamp-2">{decision.reasoning}</p>

      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{decision.timeHorizon}</span>
        <span>{Math.round(decision.confidence * 100)}% confidence</span>
        {decision.stopPrice && <span>stop {decision.stopPrice}</span>}
      </div>

      {decision.rejectionReasons.length > 0 && (
        <div className="space-y-0.5">
          {decision.rejectionReasons.map((r) => (
            <p key={r} className="text-[10px] text-bearish">
              ↯ {r}
            </p>
          ))}
        </div>
      )}

      {canAct && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => onExecute?.(decision.id)}
            className="flex-1 rounded bg-bullish/20 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-bullish hover:bg-bullish/30"
          >
            Execute
          </button>
          <button
            onClick={() => onReject?.(decision.id)}
            className="flex-1 rounded bg-bearish/20 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-bearish hover:bg-bearish/30"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}

export function DecisionQueue({ decisions, mode, onExecute, onReject }: Props) {
  const pending = decisions.filter((d) => d.status === "approved" && mode === "assisted");
  const recent = decisions.filter((d) => d.status !== "approved" || mode !== "assisted");

  return (
    <PanelShell
      title="Decision Queue"
      rightSlot={pending.length > 0 ? `${pending.length} pending` : undefined}
    >
      {decisions.length === 0 ? (
        <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
          No decisions yet
        </p>
      ) : (
        <div className="space-y-2 p-3">
          {pending.length > 0 && (
            <>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Pending approval
              </p>
              {pending.map((d) => (
                <DecisionCard
                  key={d.id}
                  decision={d}
                  mode={mode}
                  onExecute={onExecute}
                  onReject={onReject}
                />
              ))}
              {recent.length > 0 && (
                <p className="pt-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Recent
                </p>
              )}
            </>
          )}
          {recent.slice(0, 10).map((d) => (
            <DecisionCard key={d.id} decision={d} mode={mode} />
          ))}
        </div>
      )}
    </PanelShell>
  );
}
