import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import { TickerLink } from "@/components/TickerLink";
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
        "inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
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
        "inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider",
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

  const [confirming, setConfirming] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  const handleExecuteClick = () => {
    if (confirming) {
      if (timerRef.current) clearTimeout(timerRef.current);
      setConfirming(false);
      onExecute?.(decision.id);
    } else {
      setConfirming(true);
      timerRef.current = setTimeout(() => setConfirming(false), 3000);
    }
  };

  const handleCancelConfirm = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setConfirming(false);
  };

  return (
    <div
      className={cn(
        "rounded-sm bg-muted/60 px-3 py-2.5 text-xs space-y-2",
        canAct && "outline-none focus-visible:ring-1 focus-visible:ring-ring",
      )}
      tabIndex={canAct ? 0 : undefined}
      aria-label={`${decision.instrument} ${decision.side} decision`}
      onKeyDown={canAct ? (e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter") {
          e.preventDefault();
          handleExecuteClick();
        } else if (e.key === "Delete" && !confirming) {
          e.preventDefault();
          onReject?.(decision.id);
        } else if (e.key === "Escape" && confirming) {
          e.preventDefault();
          handleCancelConfirm();
        }
      } : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <TickerLink symbol={decision.instrument} className="font-mono font-semibold" />
          <SideBadge side={decision.side} />
          <StatusBadge status={decision.status} />
        </div>
        <span className={cn("font-mono text-[11px]", pnlColor)}>
          ${parseFloat(decision.sizeUsd).toFixed(2)}
        </span>
      </div>

      <p className="text-muted-foreground line-clamp-2">{decision.reasoning}</p>

      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{decision.timeHorizon}</span>
        <span>{Math.round(decision.confidence * 100)}% confidence</span>
        {decision.stopPrice && <span>stop {decision.stopPrice}</span>}
      </div>

      {decision.rejectionReasons.length > 0 && (
        <div className="space-y-0.5">
          {decision.rejectionReasons.map((r) => (
            <p key={r} className="text-[11px] text-bearish">
              ↯ {r}
            </p>
          ))}
        </div>
      )}

      {canAct && (
        <div className="flex gap-2 pt-1">
          {confirming ? (
            <>
              <button
                onClick={handleExecuteClick}
                aria-label={`Confirm execution of ${decision.instrument} ${decision.side} order`}
                className="flex-1 rounded bg-warning/20 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-warning transition-colors hover:bg-warning/30 active:bg-warning/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-11 pointer-coarse:py-2.5"
              >
                Confirm?
              </button>
              <button
                onClick={handleCancelConfirm}
                aria-label="Cancel execution"
                className="flex-1 rounded bg-muted px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:bg-muted/60 active:bg-muted/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-11 pointer-coarse:py-2.5"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                onClick={handleExecuteClick}
                aria-label={`Execute ${decision.instrument} ${decision.side} order`}
                className="flex-1 rounded bg-bullish/20 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-bullish transition-colors hover:bg-bullish/30 active:bg-bullish/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-11 pointer-coarse:py-2.5"
              >
                Execute
              </button>
              <button
                onClick={() => onReject?.(decision.id)}
                aria-label={`Reject ${decision.instrument} ${decision.side} decision`}
                className="flex-1 rounded bg-bearish/20 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-bearish transition-colors hover:bg-bearish/30 active:bg-bearish/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-11 pointer-coarse:py-2.5"
              >
                Reject
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function DecisionQueue({ decisions, mode, onExecute, onReject }: Props) {
  const pending = useMemo(
    () => decisions.filter((d) => d.status === "approved" && mode === "assisted"),
    [decisions, mode],
  );
  const recent = useMemo(
    () => decisions.filter((d) => d.status !== "approved" || mode !== "assisted"),
    [decisions, mode],
  );

  return (
    <PanelShell
      title="DECISION QUEUE"
      rightSlot={pending.length > 0 ? `${pending.length} PENDING` : undefined}
      className={pending.length > 0 ? "border-warning/50 bg-warning/5" : undefined}
    >
      {/* Announce pending approvals to screen readers immediately */}
      <span className="sr-only" aria-live="assertive" aria-atomic="true">
        {pending.length > 0
          ? `${pending.length} decision${pending.length !== 1 ? "s" : ""} pending approval`
          : ""}
      </span>
      {decisions.length === 0 ? (
        <p className="px-3 py-6 text-center text-[11px] text-muted-foreground">
          no decisions yet
        </p>
      ) : (
        <div className="space-y-2 p-3">
          {pending.length > 0 && (
            <>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                PENDING APPROVAL
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
                <p className="pt-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  RECENT
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
