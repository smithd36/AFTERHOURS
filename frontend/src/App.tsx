import { cn } from "@/lib/utils";
import { MarketWatch } from "@/components/panels/MarketWatch";
import { useEventStream } from "@/hooks/useEventStream";
import { useMarketTicks } from "@/hooks/useMarketTicks";

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
  const { ticks, handleEnvelope } = useMarketTicks();
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
        <div className="mx-auto max-w-2xl space-y-3">
          <MarketWatch ticks={ticks} />
        </div>
      </main>
    </div>
  );
}
