import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Brain,
  CandlestickChart,
  Gauge,
  Gavel,
  Radio,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CalibrationPanel } from "@/components/panels/CalibrationPanel";
import { DecisionQueue } from "@/components/panels/DecisionQueue";
import { FeedHealthBar } from "@/components/panels/FeedHealthBar";
import { MarketWatch } from "@/components/panels/MarketWatch";
import { PortfolioPanel } from "@/components/panels/PortfolioPanel";
import { SignalFeed } from "@/components/panels/SignalFeed";
import { ThesisFeed } from "@/components/panels/ThesisFeed";
import { WatchlistPanel } from "@/components/panels/WatchlistPanel";
import { useBackfill } from "@/hooks/useBackfill";
import { useCalibration } from "@/hooks/useCalibration";
import { useDecisions } from "@/hooks/useDecisions";
import { useEventStream } from "@/hooks/useEventStream";
import { useFeedHealth } from "@/hooks/useFeedHealth";
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

/**
 * Subscribe to a CSS media query. Drives the desktop↔mobile branch so each
 * panel mounts exactly once (no hidden duplicate running effects/animations).
 */
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : true,
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

type TabId = "markets" | "signals" | "theses" | "decisions" | "book" | "calib";

interface TabDef {
  id: TabId;
  label: string;
  icon: LucideIcon;
  badge?: number;
}

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
      <span className="whitespace-nowrap font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
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
            "flex items-center justify-center rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider transition-[color,border-color,background-color] duration-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-11 pointer-coarse:px-3 pointer-coarse:text-[11px]",
            mode === m
              ? MODE_STYLES[m]
              : "border-border text-muted-foreground/50 hover:border-muted-foreground/60 hover:text-muted-foreground active:border-muted-foreground/60 active:text-muted-foreground",
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
        "flex items-center justify-center rounded border border-bearish px-3 py-0.5 text-[10px] font-bold uppercase tracking-wider text-bearish transition-colors hover:bg-bearish/20 active:bg-bearish/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-bearish pointer-coarse:min-h-11 pointer-coarse:px-4 pointer-coarse:text-[11px]",
        pulsing && "halt-pulsing",
      )}
    >
      HALT
    </button>
  );
}

function MobileTabBar({
  tabs,
  active,
  onChange,
}: {
  tabs: TabDef[];
  active: TabId;
  onChange: (id: TabId) => void;
}) {
  return (
    <nav
      aria-label="Panels"
      className="grid shrink-0 grid-cols-6 border-t border-border bg-card pb-[env(safe-area-inset-bottom)]"
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = active === tab.id;
        const pending = tab.badge != null && tab.badge > 0 ? tab.badge : 0;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onChange(tab.id)}
            aria-current={isActive ? "page" : undefined}
            aria-label={
              pending > 0
                ? `${tab.label}, ${pending} pending approval${pending !== 1 ? "s" : ""}`
                : undefined
            }
            className={cn(
              "relative flex min-h-13 flex-col items-center justify-center gap-1 py-2 text-[10px] font-medium uppercase tracking-wider transition-colors duration-150 active:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
              isActive
                ? "text-foreground"
                : "text-muted-foreground/60 hover:text-muted-foreground",
            )}
          >
            {isActive && (
              <span className="absolute inset-x-4 top-0 h-0.5 rounded-full bg-foreground" />
            )}
            <span className="relative">
              <Icon className="h-5 w-5" strokeWidth={isActive ? 2.25 : 1.75} />
              {pending > 0 && (
                <span
                  aria-hidden="true"
                  className="absolute -right-2.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-warning px-1 text-[9px] font-bold tabular-nums text-background"
                >
                  {pending > 9 ? "9+" : pending}
                </span>
              )}
            </span>
            <span className="max-w-full truncate px-0.5">{tab.label}</span>
          </button>
        );
      })}
    </nav>
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
  const { feeds: feedHealth, handleEnvelope: handleFeedHealth } = useFeedHealth();

  const handleEnvelope = useCallback(
    (envelope: EventEnvelope) => {
      handleTick(envelope);
      handleSignal(envelope);
      handleThesis(envelope);
      handleDecision(envelope);
      handleCalibration(envelope);
      handleWatchlist(envelope);
      handleFeedHealth(envelope);
    },
    [
      handleTick,
      handleSignal,
      handleThesis,
      handleDecision,
      handleCalibration,
      handleWatchlist,
      handleFeedHealth,
    ],
  );

  const { connected } = useEventStream(handleEnvelope);
  useBackfill(handleEnvelope);

  // ── Responsive shell ──────────────────────────────────────────────────────
  // Desktop keeps the multi-column grid. Below lg the panels become a single
  // full-height view switched by a bottom tab bar (see MobileTabBar). One
  // branch renders at a time, so each panel mounts once.
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const [activeTab, setActiveTab] = useState<TabId>("markets");

  // Pending approvals mirror DecisionQueue's own filter — drives the tab badge.
  const pendingCount = useMemo(
    () =>
      decisions.filter((d) => d.status === "approved" && mode === "assisted")
        .length,
    [decisions, mode],
  );

  // Panel elements, built once so both shells share a single source of props.
  const marketWatch = <MarketWatch ticks={ticks} />;
  const signalFeed = <SignalFeed signals={signals} />;
  const thesisFeed = <ThesisFeed theses={theses} />;
  const decisionQueue = (
    <DecisionQueue
      decisions={decisions}
      mode={mode}
      onExecute={handleExecute}
      onReject={handleReject}
    />
  );
  const watchlist = (
    <WatchlistPanel
      entries={watchlistEntries}
      loading={watchlistLoading}
      ticks={ticks}
      onAdd={watchlistAdd}
      onRemove={watchlistRemove}
    />
  );
  const portfolio = <PortfolioPanel snapshot={snapshot} decisions={decisions} />;
  const calibration = <CalibrationPanel report={report} gates={gates} />;

  const tabs: TabDef[] = [
    { id: "markets", label: "Markets", icon: CandlestickChart },
    { id: "signals", label: "Signals", icon: Radio },
    { id: "theses", label: "Theses", icon: Brain },
    { id: "decisions", label: "Decisions", icon: Gavel, badge: pendingCount },
    { id: "book", label: "Book", icon: Wallet },
    { id: "calib", label: "Calib", icon: Gauge },
  ];

  const mobilePanel: Record<TabId, ReactNode> = {
    markets: marketWatch,
    signals: signalFeed,
    theses: thesisFeed,
    decisions: decisionQueue,
    book: (
      <div className="space-y-2">
        {watchlist}
        {portfolio}
      </div>
    ),
    calib: calibration,
  };

  return (
    <div className="flex h-[100dvh] w-full flex-col bg-background text-foreground pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
      <header
        className="terminal-header flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] sm:px-4"
        data-mode={mode}
      >
        <span className="brand-logo order-1 text-xs font-semibold tracking-[0.25em] text-muted-foreground">
          AFTERHOURS
        </span>
        {/* Controls: own full-width row on phones, inline on the right at sm+. */}
        <div className="order-3 flex w-full items-center justify-between gap-2 sm:order-2 sm:ml-auto sm:w-auto sm:justify-end sm:gap-3">
          <ModeIndicator mode={mode} onChange={handleModeChange} />
          <HaltButton onHalt={handleHalt} pulsing={mode === "assisted"} />
        </div>
        <div className="order-2 ml-auto flex items-center gap-2 sm:order-3 sm:ml-0 sm:gap-3">
          <MarketClock />
          <ConnectionPip connected={connected} />
        </div>
      </header>

      <FeedHealthBar feeds={feedHealth} />

      {isDesktop ? (
        <main className="flex-1 overflow-auto p-4">
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2 xl:grid-cols-3">
            {/* Row 1: live market data */}
            <div className="xl:col-span-2">{marketWatch}</div>
            {signalFeed}

            {/* Row 2: analysis + action */}
            <div className="xl:col-span-2">{thesisFeed}</div>
            {decisionQueue}

            {/* Row 3: utilities */}
            {watchlist}
            {portfolio}
            {calibration}
          </div>
        </main>
      ) : (
        <>
          {/* DecisionQueue's own live region only exists while its tab is
              mounted; this shell-level one covers pending approvals raised
              while another tab is in view. Gated off on the decisions tab so
              the two don't announce twice. */}
          {activeTab !== "decisions" && (
            <span className="sr-only" aria-live="assertive" aria-atomic="true">
              {pendingCount > 0
                ? `${pendingCount} decision${pendingCount !== 1 ? "s" : ""} pending approval`
                : ""}
            </span>
          )}
          {/* key resets scroll position and replays the enter fade per tab. */}
          <main
            key={activeTab}
            className="tab-panel flex-1 overflow-auto p-2"
          >
            {mobilePanel[activeTab]}
          </main>
          <MobileTabBar tabs={tabs} active={activeTab} onChange={setActiveTab} />
        </>
      )}
    </div>
  );
}
