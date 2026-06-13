import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { CalibrationPanel } from "@/components/panels/CalibrationPanel";
import { DecisionQueue } from "@/components/panels/DecisionQueue";
import { MarketWatch } from "@/components/panels/MarketWatch";
import { PortfolioPanel } from "@/components/panels/PortfolioPanel";
import { SignalFeed } from "@/components/panels/SignalFeed";
import { ThesisFeed } from "@/components/panels/ThesisFeed";
import { WatchlistPanel } from "@/components/panels/WatchlistPanel";
import { useBackfill } from "@/hooks/useBackfill";
import { useCalibration } from "@/hooks/useCalibration";
import { useDecisions } from "@/hooks/useDecisions";
import { useEventStream } from "@/hooks/useEventStream";
import { useMarketTicks } from "@/hooks/useMarketTicks";
import { usePortfolio } from "@/hooks/usePortfolio";
import { useSignals } from "@/hooks/useSignals";
import { useTheses } from "@/hooks/useTheses";
import { useWatchlist } from "@/hooks/useWatchlist";
import type { EventEnvelope } from "@/types/core";

type AutonomyMode = "observe" | "paper" | "assisted";

const MODE_STYLES: Record<AutonomyMode, string> = {
  observe: "border-muted-foreground/70 bg-muted/50 text-muted-foreground",
  paper: "border-bullish bg-bullish/10 text-bullish",
  assisted: "border-warning bg-warning/10 text-warning",
};

const _ET_TIME_FMT = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function _isNyseOpen(d: Date): boolean {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "numeric",
    minute: "numeric",
    hour12: false,
  }).formatToParts(d);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const dow = get("weekday");
  if (dow === "Sat" || dow === "Sun") return false;
  const h = parseInt(get("hour"), 10);
  const m = parseInt(get("minute"), 10);
  const mins = h * 60 + m;
  return mins >= 9 * 60 + 30 && mins < 16 * 60;
}

function MarketClock() {
  const [now, setNow] = useState(() => new Date());
  const rafRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const tick = () => {
      setNow(new Date());
      // align to the next whole second
      rafRef.current = setTimeout(tick, 1000 - (Date.now() % 1000));
    };
    rafRef.current = setTimeout(tick, 1000 - (Date.now() % 1000));
    return () => { if (rafRef.current) clearTimeout(rafRef.current); };
  }, []);

  const open = _isNyseOpen(now);
  const timeStr = _ET_TIME_FMT.format(now);

  return (
    <div className="flex items-center gap-1.5">
      <span
        className={cn(
          "inline-block h-1.5 w-1.5 rounded-full",
          open ? "bg-bullish" : "bg-muted-foreground/50",
        )}
      />
      <span className="hidden sm:inline font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        {timeStr} ET&nbsp;·&nbsp;
        <span className={open ? "text-bullish" : "text-muted-foreground/60"}>
          {open ? "open" : "closed"}
        </span>
      </span>
    </div>
  );
}

function ConnectionPip({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={cn(
          "inline-block h-1.5 w-1.5 rounded-full",
          connected ? "bg-bullish" : "bg-bearish",
        )}
      />
      <span className="hidden sm:inline text-[11px] uppercase tracking-widest text-muted-foreground">
        {connected ? "live" : "offline"}
      </span>
    </div>
  );
}

function ModeIndicator({
  mode,
  onChange,
}: {
  mode: AutonomyMode;
  onChange: (m: AutonomyMode) => void;
}) {
  const modes: AutonomyMode[] = ["observe", "paper", "assisted"];
  return (
    <div className="flex items-center gap-1">
      {modes.map((m, i) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          aria-pressed={mode === m}
          aria-keyshortcuts={String(i + 1)}
          title={`${m[0].toUpperCase()}${m.slice(1)} mode [${i + 1}]`}
          className={cn(
            "rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider transition-[color,border-color,background-color] duration-300",
            mode === m
              ? MODE_STYLES[m]
              : "border-border text-muted-foreground/50 hover:border-muted-foreground/60 hover:text-muted-foreground",
          )}
        >
          {m}
        </button>
      ))}
    </div>
  );
}

function HaltButton({ onHalt, pulsing }: { onHalt: () => void; pulsing?: boolean }) {
  return (
    <button
      onClick={onHalt}
      title="Halt all activity [H]"
      aria-keyshortcuts="h"
      className={cn(
        "rounded border border-bearish px-3 py-0.5 text-[10px] font-bold uppercase tracking-wider text-bearish transition-colors hover:bg-bearish/20",
        pulsing && "halt-pulsing",
      )}
    >
      HALT
    </button>
  );
}

export default function App() {
  const [mode, setMode] = useState<AutonomyMode>("observe");

  // Fetch initial mode
  useEffect(() => {
    fetch("/api/mode")
      .then((r) => r.json())
      .then((d: { mode: AutonomyMode }) => setMode(d.mode))
      .catch(() => {});
  }, []);

  const handleModeChange = useCallback(async (newMode: AutonomyMode) => {
    try {
      const res = await fetch("/api/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: newMode }),
      });
      const data = (await res.json()) as { mode: AutonomyMode };
      setMode(data.mode);
    } catch {
      // ignore network errors
    }
  }, []);

  const handleHalt = useCallback(async () => {
    try {
      await fetch("/api/halt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "operator_halt" }),
      });
      setMode("observe");
    } catch {
      // ignore
    }
  }, []);

  const handleExecute = useCallback(async (id: string) => {
    await fetch(`/api/decisions/${id}/execute`, { method: "POST" });
  }, []);

  const handleReject = useCallback(async (id: string) => {
    await fetch(`/api/decisions/${id}/reject`, { method: "POST" });
  }, []);

  // Global keyboard shortcuts: H = halt, 1/2/3 = mode. Skipped inside inputs.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      switch (e.key) {
        case "h":
        case "H":
          e.preventDefault();
          void handleHalt();
          break;
        case "1":
          e.preventDefault();
          void handleModeChange("observe");
          break;
        case "2":
          e.preventDefault();
          void handleModeChange("paper");
          break;
        case "3":
          e.preventDefault();
          void handleModeChange("assisted");
          break;
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [handleHalt, handleModeChange]);

  const { ticks, handleEnvelope: handleTick } = useMarketTicks();
  const { snapshot } = usePortfolio();
  const { report, gates, handleEnvelope: handleCalibration } = useCalibration();
  const {
    entries: watchlistEntries,
    loading: watchlistLoading,
    add: watchlistAdd,
    remove: watchlistRemove,
    handleEnvelope: handleWatchlist,
  } = useWatchlist();

  const activeInstruments = useMemo(
    () =>
      watchlistLoading
        ? null
        : new Set(watchlistEntries.map((e) => e.instrument)),
    [watchlistEntries, watchlistLoading],
  );

  const { signals, handleEnvelope: handleSignal } = useSignals(activeInstruments);
  const { theses, handleEnvelope: handleThesis } = useTheses(activeInstruments);
  const { decisions, handleEnvelope: handleDecision } = useDecisions(activeInstruments);

  const handleEnvelope = useCallback(
    (envelope: EventEnvelope) => {
      handleTick(envelope);
      handleSignal(envelope);
      handleThesis(envelope);
      handleDecision(envelope);
      handleCalibration(envelope);
      handleWatchlist(envelope);
    },
    [handleTick, handleSignal, handleThesis, handleDecision, handleCalibration, handleWatchlist],
  );

  const { connected } = useEventStream(handleEnvelope);
  useBackfill(handleEnvelope);

  return (
    <div className="flex h-screen w-screen flex-col bg-background text-foreground">
      <header
        className="terminal-header flex items-center justify-between border-b border-border px-4 py-2"
        data-mode={mode}
      >
        <span className="brand-logo text-xs font-semibold tracking-[0.25em] text-muted-foreground">
          AFTERHOURS
        </span>
        <div className="flex items-center gap-2 sm:gap-3">
          <ModeIndicator mode={mode} onChange={handleModeChange} />
          <HaltButton onHalt={handleHalt} pulsing={mode === "assisted"} />
          <MarketClock />
          <ConnectionPip connected={connected} />
        </div>
      </header>

      <main className="flex-1 overflow-auto p-4">
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-2 xl:grid-cols-3">
          {/* Row 1: live market data */}
          <div className="xl:col-span-2">
            <MarketWatch ticks={ticks} />
          </div>
          <SignalFeed signals={signals} />

          {/* Row 2: analysis + action */}
          <div className="xl:col-span-2">
            <ThesisFeed theses={theses} />
          </div>
          <DecisionQueue
            decisions={decisions}
            mode={mode}
            onExecute={handleExecute}
            onReject={handleReject}
          />

          {/* Row 3: utilities */}
          <WatchlistPanel
            entries={watchlistEntries}
            loading={watchlistLoading}
            ticks={ticks}
            onAdd={watchlistAdd}
            onRemove={watchlistRemove}
          />
          <PortfolioPanel snapshot={snapshot} />
          <CalibrationPanel report={report} gates={gates} />
        </div>
      </main>
    </div>
  );
}
