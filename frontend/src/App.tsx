import { cn } from "@/lib/utils";
import { MarketWatch } from "@/components/panels/MarketWatch";
import { SignalFeed } from "@/components/panels/SignalFeed";
import { ThesisFeed } from "@/components/panels/ThesisFeed";
import { useEventStream } from "@/hooks/useEventStream";
import { useMarketTicks } from "@/hooks/useMarketTicks";
import { useSignals } from "@/hooks/useSignals";
import { useTheses } from "@/hooks/useTheses";
import type { EventEnvelope } from "@/types/core";

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

export default function App() {
  const { ticks, handleEnvelope: handleTick } = useMarketTicks();
  const { signals, handleEnvelope: handleSignal } = useSignals();
  const { theses, handleEnvelope: handleThesis } = useTheses();

  const handleEnvelope = (envelope: EventEnvelope) => {
    handleTick(envelope);
    handleSignal(envelope);
    handleThesis(envelope);
  };

  const { connected } = useEventStream(handleEnvelope);

  return (
    <div className="flex h-screen w-screen flex-col bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="text-xs font-semibold tracking-[0.25em] text-muted-foreground">
          AFTERHOURS
        </span>
        <ConnectionPip connected={connected} />
      </header>

      <main className="flex-1 overflow-auto p-4">
        <div className="mx-auto grid max-w-5xl grid-cols-1 gap-3 lg:grid-cols-2">
          <MarketWatch ticks={ticks} />
          <SignalFeed signals={signals} />
          <ThesisFeed theses={theses} />
        </div>
      </main>
    </div>
  );
}
