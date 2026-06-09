import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { DecisionQueue } from "@/components/panels/DecisionQueue";
import { MarketWatch } from "@/components/panels/MarketWatch";
import { PortfolioPanel } from "@/components/panels/PortfolioPanel";
import { SignalFeed } from "@/components/panels/SignalFeed";
import { ThesisFeed } from "@/components/panels/ThesisFeed";
import { useDecisions } from "@/hooks/useDecisions";
import { useEventStream } from "@/hooks/useEventStream";
import { useMarketTicks } from "@/hooks/useMarketTicks";
import { usePortfolio } from "@/hooks/usePortfolio";
import { useSignals } from "@/hooks/useSignals";
import { useTheses } from "@/hooks/useTheses";
import type { EventEnvelope } from "@/types/core";

type AutonomyMode = "observe" | "paper" | "assisted";

const MODE_STYLES: Record<AutonomyMode, string> = {
  observe: "border-muted-foreground text-muted-foreground",
  paper: "border-bullish text-bullish",
  assisted: "border-yellow-500 text-yellow-500",
};

function ConnectionPip({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={cn(
          "inline-block h-1.5 w-1.5 rounded-full",
          connected ? "bg-bullish" : "bg-bearish",
        )}
      />
      <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
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
      {modes.map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={cn(
            "rounded border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider transition-colors",
            mode === m
              ? MODE_STYLES[m]
              : "border-border text-muted-foreground hover:border-muted-foreground",
          )}
        >
          {m}
        </button>
      ))}
    </div>
  );
}

function HaltButton({ onHalt }: { onHalt: () => void }) {
  return (
    <button
      onClick={onHalt}
      className="rounded border border-bearish px-3 py-0.5 text-[9px] font-bold uppercase tracking-wider text-bearish hover:bg-bearish/20"
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

  const { ticks, handleEnvelope: handleTick } = useMarketTicks();
  const { signals, handleEnvelope: handleSignal } = useSignals();
  const { theses, handleEnvelope: handleThesis } = useTheses();
  const { decisions, handleEnvelope: handleDecision } = useDecisions();
  const { snapshot } = usePortfolio();

  const handleEnvelope = useCallback(
    (envelope: EventEnvelope) => {
      handleTick(envelope);
      handleSignal(envelope);
      handleThesis(envelope);
      handleDecision(envelope);
    },
    [handleTick, handleSignal, handleThesis, handleDecision],
  );

  const { connected } = useEventStream(handleEnvelope);

  return (
    <div className="flex h-screen w-screen flex-col bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="text-xs font-semibold tracking-[0.25em] text-muted-foreground">
          AFTERHOURS
        </span>
        <div className="flex items-center gap-3">
          <ModeIndicator mode={mode} onChange={handleModeChange} />
          <HaltButton onHalt={handleHalt} />
          <ConnectionPip connected={connected} />
        </div>
      </header>

      <main className="flex-1 overflow-auto p-4">
        <div className="mx-auto grid max-w-6xl grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
          <MarketWatch ticks={ticks} />
          <SignalFeed signals={signals} />
          <ThesisFeed theses={theses} />
          <DecisionQueue
            decisions={decisions}
            mode={mode}
            onExecute={handleExecute}
            onReject={handleReject}
          />
          <PortfolioPanel snapshot={snapshot} />
        </div>
      </main>
    </div>
  );
}
