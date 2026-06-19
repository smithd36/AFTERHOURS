import { useState } from "react";
import { ChevronDown, Plus, RotateCw, Sparkles, Telescope } from "lucide-react";
import { cn } from "@/lib/utils";
import { PanelShell } from "@/components/layout/PanelShell";
import { TickerLink } from "@/components/TickerLink";
import {
  useDiscovery,
  type DiscoveryAnalysis,
  type DiscoveryCandidate,
  type DiscoveryContribution,
} from "@/hooks/useDiscovery";

// Colour groups by factor family (mirrors SignalFeed's source badges): a label
// for the family + a hue. Unknown factors fall back to a neutral chip.
const FACTOR_BADGE: Record<string, { label: string; className: string }> = {
  insider_activity: { label: "INSIDER", className: "bg-bullish/15 text-bullish" },
  government_exposure: { label: "GOV", className: "bg-bearish/15 text-bearish" },
  supply_chain: { label: "SUPPLY", className: "bg-muted text-muted-foreground" },
  news: { label: "NEWS", className: "bg-info/15 text-info" },
};

function factorBadge(factor: string): { label: string; className: string } {
  return FACTOR_BADGE[factor] ?? { label: factor.toUpperCase(), className: "bg-muted text-muted-foreground" };
}

function ageDaysLabel(days: number): string {
  if (days < 1) return "<1d";
  if (days < 14) return `${Math.round(days)}d`;
  return `${Math.round(days / 7)}w`;
}

function FactorChip({ factor }: { factor: string }) {
  const { label, className } = factorBadge(factor);
  return (
    <span
      className={cn(
        "shrink-0 rounded-sm px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        className,
      )}
    >
      {label}
    </span>
  );
}

function ContributionRow({ c }: { c: DiscoveryContribution }) {
  const bearish = c.weight < 0;
  const { label } = factorBadge(c.factor);
  return (
    <div className="flex items-start gap-2 px-3 py-1.5">
      <span
        className={cn(
          "mt-px shrink-0 text-[10px] font-semibold uppercase tracking-wider tabular-nums",
          bearish ? "text-bearish" : "text-bullish",
        )}
        title={`${label} contribution ${bearish ? "(bearish)" : "(bullish)"}`}
      >
        {bearish ? "−" : "+"}
        {Math.abs(c.weight).toFixed(2)}
      </span>
      <span className="min-w-0 flex-1 text-[11px] leading-snug text-muted-foreground">
        {c.summary}
      </span>
      <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/60">
        {ageDaysLabel(c.age_days)}
      </span>
    </div>
  );
}

function CandidateRow({
  candidate,
  onAdd,
}: {
  candidate: DiscoveryCandidate;
  onAdd?: (instrument: string, market: "crypto" | "equity") => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [adding, setAdding] = useState(false);
  const [analysis, setAnalysis] = useState<DiscoveryAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const pct = Math.round(candidate.score * 100);

  const analyze = async () => {
    if (analyzing) return;
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      const r = await fetch(
        `/api/discovery/${encodeURIComponent(candidate.instrument)}/analysis`,
      );
      if (!r.ok) {
        throw new Error(r.status === 503 ? "analyst unavailable" : `HTTP ${r.status}`);
      }
      setAnalysis((await r.json()) as DiscoveryAnalysis);
    } catch (e: unknown) {
      setAnalyzeError(String(e));
    } finally {
      setAnalyzing(false);
    }
  };

  const handleAdd = async () => {
    if (!onAdd || adding) return;
    setAdding(true);
    try {
      // 6B.1 candidates are disclosure-driven equities (ADR-012); crypto
      // breadth arrives in 6B.2 and will carry its own market.
      await onAdd(candidate.instrument, "equity");
    } catch {
      setAdding(false); // leave it visible so the operator can retry
    }
  };

  return (
    <div className="border-b border-border/40">
      <div className="flex items-center gap-2 px-3 py-2 hover:bg-muted/20 transition-colors duration-75">
        <TickerLink
          symbol={candidate.instrument}
          className="shrink-0 font-mono text-xs font-semibold text-foreground"
        />
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          aria-label={`${expanded ? "Hide" : "Show"} evidence for ${candidate.instrument}`}
          className="flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm"
        >
          <ChevronDown
            aria-hidden="true"
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-transform duration-200",
              !expanded && "-rotate-90",
            )}
          />
          {/* Score bar */}
          <span className="flex items-center gap-1.5">
            <span className="h-1 w-16 overflow-hidden rounded-full bg-muted">
              <span
                className="block h-full rounded-full bg-foreground/70"
                style={{ width: `${pct}%` }}
              />
            </span>
            <span className="text-[11px] tabular-nums text-muted-foreground">
              {candidate.score.toFixed(2)}
            </span>
          </span>
          <span className="flex min-w-0 flex-wrap items-center gap-1">
            {candidate.factors.map((f) => (
              <FactorChip key={f} factor={f} />
            ))}
          </span>
        </button>

        {onAdd && (
          <button
            type="button"
            onClick={handleAdd}
            disabled={adding}
            title={`Add ${candidate.instrument} to watchlist`}
            aria-label={`Add ${candidate.instrument} to watchlist`}
            className="flex shrink-0 items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:border-bullish/60 hover:text-bullish disabled:opacity-50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-9 pointer-coarse:px-2"
          >
            <Plus className="h-3 w-3" strokeWidth={2} />
            Watch
          </button>
        )}
      </div>

      {expanded && (
        <div className="bg-muted/10 pb-2">
          {candidate.contributions.map((c, i) => (
            <ContributionRow key={`${c.factor}-${i}`} c={c} />
          ))}

          <div className="px-3 pt-1.5">
            {analysis ? (
              <div className="space-y-2 rounded-sm border border-border/60 bg-card/40 p-2">
                <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  <Sparkles className="h-3 w-3" aria-hidden="true" /> AI analyst
                </p>
                {analysis.thesis && (
                  <p className="text-[11px] leading-snug text-foreground">{analysis.thesis}</p>
                )}
                {analysis.risks.length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-bearish">
                      Counter-signals
                    </p>
                    <ul className="mt-0.5 space-y-0.5">
                      {analysis.risks.map((risk, i) => (
                        <li key={i} className="text-[11px] leading-snug text-muted-foreground">
                          • {risk}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {analysis.suggested_step && (
                  <p className="text-[11px] leading-snug text-muted-foreground">
                    <span className="text-muted-foreground/60">Next: </span>
                    {analysis.suggested_step}
                  </p>
                )}
              </div>
            ) : (
              <button
                type="button"
                onClick={analyze}
                disabled={analyzing}
                className="flex items-center gap-1.5 rounded border border-border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:border-info/60 hover:text-info disabled:opacity-50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-9 pointer-coarse:px-2"
              >
                <Sparkles
                  className={cn("h-3 w-3", analyzing && "animate-pulse")}
                  aria-hidden="true"
                />
                {analyzing ? "Analyzing…" : "Analyze with AI"}
              </button>
            )}
            {analyzeError && (
              <p className="mt-1 text-[10px] text-bearish">{analyzeError}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface DiscoveryFeedProps {
  onAdd?: (instrument: string, market: "crypto" | "equity") => Promise<void>;
}

export function DiscoveryFeed({ onAdd }: DiscoveryFeedProps) {
  const { candidates, loading, error, refresh } = useDiscovery();

  // After an add the name is now watched, so re-running the projection drops it
  // from the feed (the backend excludes watched instruments).
  const handleAdd = onAdd
    ? async (instrument: string, market: "crypto" | "equity") => {
        await onAdd(instrument, market);
        refresh();
      }
    : undefined;

  const count = candidates.length;
  const rightSlot = (
    <span className="flex items-center gap-2">
      {count > 0 && (
        <span className="tabular-nums">
          {count} {count === 1 ? "CANDIDATE" : "CANDIDATES"}
        </span>
      )}
      <button
        type="button"
        onClick={refresh}
        title="Refresh candidates"
        aria-label="Refresh candidates"
        className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:h-9 pointer-coarse:w-9"
      >
        <RotateCw className={cn("h-3 w-3", loading && "animate-spin")} aria-hidden="true" />
      </button>
    </span>
  );

  return (
    <PanelShell title="DISCOVERY" rightSlot={rightSlot} className="flex h-full flex-col">
      {error ? (
        <p className="px-3 py-6 text-center text-[11px] text-bearish">
          couldn't load candidates — {error}
        </p>
      ) : count === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
          <Telescope
            aria-hidden="true"
            className="h-8 w-8 text-muted-foreground/40"
            strokeWidth={1.5}
          />
          <div className="space-y-1">
            <p className="text-sm font-medium text-muted-foreground">
              {loading ? "Scanning for opportunities…" : "No candidates yet"}
            </p>
            <p className="max-w-xs text-xs text-muted-foreground/60">
              Ranked opportunities fused from multiple weak signals surface here. They
              grow as alt-data and news disclosures accumulate on unwatched names.
            </p>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          {candidates.map((candidate) => (
            <CandidateRow key={candidate.instrument} candidate={candidate} onAdd={handleAdd} />
          ))}
        </div>
      )}
    </PanelShell>
  );
}
