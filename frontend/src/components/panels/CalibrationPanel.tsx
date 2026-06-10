import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import type {
  CalibrationBucket,
  CalibrationReport,
  GatesReport,
  GateStatus,
} from "@/hooks/useCalibration";

interface Props {
  report: CalibrationReport | null;
  gates: GatesReport | null;
}

function eceColor(ece: number): string {
  // Thresholds follow the Appendix B gates: ≤0.12 clears every gate,
  // ≤0.18 clears Observe → Paper, anything above clears nothing.
  if (ece <= 0.12) return "text-bullish";
  if (ece <= 0.18) return "text-warning";
  return "text-bearish";
}

function ReliabilityRow({ bucket }: { bucket: CalibrationBucket }) {
  const conf = bucket.avg_confidence ?? 0;
  const hit = bucket.hit_rate ?? 0;
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className="w-14 shrink-0 font-mono text-muted-foreground">
        {bucket.lo.toFixed(1)}–{bucket.hi.toFixed(1)}
      </span>
      {/* bar = realized hit rate; tick = stated confidence */}
      <div className="relative h-2 flex-1 overflow-hidden rounded-sm bg-muted">
        <div
          className={cn(
            "absolute inset-y-0 left-0",
            hit >= conf ? "bg-bullish/60" : "bg-bearish/60",
          )}
          style={{ width: `${(hit * 100).toFixed(0)}%` }}
        />
        <div
          className="absolute inset-y-0 w-px bg-foreground"
          style={{ left: `${(conf * 100).toFixed(0)}%` }}
        />
      </div>
      <span className="w-20 shrink-0 text-right font-mono text-muted-foreground">
        {(hit * 100).toFixed(0)}% · n={bucket.n}
      </span>
    </div>
  );
}

function GateCard({ title, gate }: { title: string; gate: GateStatus }) {
  return (
    <div className="rounded border border-border p-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-semibold">{title}</span>
        <span
          className={cn(
            "inline-block rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider",
            gate.ready ? "bg-bullish/20 text-bullish" : "bg-muted text-muted-foreground",
          )}
        >
          {gate.ready ? "ready" : "not ready"}
        </span>
      </div>
      <div className="mt-1.5 space-y-0.5">
        {gate.criteria.map((c) => (
          <div key={c.name} className="flex items-center justify-between text-[10px]">
            <span className={c.passed ? "text-bullish" : "text-muted-foreground"}>
              {c.passed ? "✓" : "·"} {c.name.replaceAll("_", " ")}
            </span>
            <span className="font-mono text-muted-foreground">
              {c.current} / {c.required}
            </span>
          </div>
        ))}
      </div>
      {gate.deferred.length > 0 && (
        <p className="mt-1.5 text-[9px] leading-relaxed text-muted-foreground/70">
          deferred: {gate.deferred.join(" · ")}
        </p>
      )}
    </div>
  );
}

export function CalibrationPanel({ report, gates }: Props) {
  const stats = report?.overall ?? null;
  const nonEmptyBuckets = stats?.buckets.filter((b) => b.n > 0) ?? [];
  const modeCounts = report
    ? Object.entries(report.by_mode).map(([mode, s]) => `${mode} ${s.n}`)
    : [];

  return (
    <PanelShell
      title="Calibration"
      rightSlot={stats && stats.n > 0 ? `${stats.n} resolved` : undefined}
    >
      <div className="space-y-3 p-3">
        {/* Headline ECE */}
        <div className="flex items-baseline justify-between rounded border border-border p-2">
          <span className="text-xs text-muted-foreground">ECE</span>
          {stats && stats.ece !== null ? (
            <span className={cn("font-mono text-lg font-semibold", eceColor(stats.ece))}>
              {stats.ece.toFixed(4)}
            </span>
          ) : (
            <span className="font-mono text-lg text-muted-foreground">—</span>
          )}
        </div>

        {modeCounts.length > 0 && (
          <p className="text-[10px] text-muted-foreground">by mode: {modeCounts.join(" · ")}</p>
        )}

        {/* Reliability bars */}
        {nonEmptyBuckets.length > 0 ? (
          <div className="space-y-1">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Reliability (bar = hit rate, tick = confidence)
            </p>
            {nonEmptyBuckets.map((b) => (
              <ReliabilityRow key={b.lo} bucket={b} />
            ))}
          </div>
        ) : (
          <p className="py-2 text-center text-[11px] text-muted-foreground">
            Awaiting resolved decisions
          </p>
        )}

        {/* Graduation gates */}
        {gates && (
          <div className="space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Autonomy gates
            </p>
            <GateCard title="Observe → Paper" gate={gates.observe_to_paper} />
            <GateCard title="Paper → Assisted" gate={gates.paper_to_assisted} />
          </div>
        )}
      </div>
    </PanelShell>
  );
}
