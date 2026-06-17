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
  LineChart,
  ListChecks,
  Radio,
  Telescope,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { AnalyticsPanel } from "@/components/panels/AnalyticsPanel";
import { CalibrationPanel } from "@/components/panels/CalibrationPanel";
import { DecisionQueue } from "@/components/panels/DecisionQueue";
import { DiscoveryFeed } from "@/components/panels/DiscoveryFeed";
import { FeedHealthBar } from "@/components/panels/FeedHealthBar";
import { MarketWatch } from "@/components/panels/MarketWatch";
import { PortfolioPanel } from "@/components/panels/PortfolioPanel";
import { SignalFeed } from "@/components/panels/SignalFeed";
import { ThesisFeed } from "@/components/panels/ThesisFeed";
import { WatchlistPanel } from "@/components/panels/WatchlistPanel";
import { WatchlistDrawer } from "@/components/layout/WatchlistDrawer";
import { useAnalytics } from "@/hooks/useAnalytics";
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

type Workspace = "discover" | "terminal" | "review";

type TabId =
  | "candidates"
  | "watchlist"
  | "markets"
  | "signals"
  | "theses"
  | "decisions"
  | "book"
  | "calib"
  | "perf";

interface TabDef {
  id: TabId;
  label: string;
  icon: LucideIcon;
  badge?: number;
}

// Each workspace owns a slice of the panels. The mobile tab bar is scoped to
// the active workspace, so it shows ≤4 tabs instead of one flat 7-tab bar.
// Discover = pre-watchlist funnel, Terminal = live pipeline, Review = outcomes.
const WORKSPACE_TABS: Record<Workspace, TabId[]> = {
  discover: ["candidates", "watchlist"],
  terminal: ["markets", "signals", "theses", "decisions"],
  review: ["book", "calib", "perf"],
};

const TAB_META: Record<TabId, { label: string; icon: LucideIcon }> = {
  candidates: { label: "Candidates", icon: Telescope },
  watchlist: { label: "Watchlist", icon: ListChecks },
  markets: { label: "Markets", icon: CandlestickChart },
  signals: { label: "Signals", icon: Radio },
  theses: { label: "Theses", icon: Brain },
  decisions: { label: "Decisions", icon: Gavel },
  book: { label: "Book", icon: Wallet },
  calib: { label: "Calib", icon: Gauge },
  perf: { label: "Perf", icon: LineChart },
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

const WORKSPACES: { id: Workspace; label: string }[] = [
  { id: "discover", label: "Discover" },
  { id: "terminal", label: "Terminal" },
  { id: "review", label: "Review" },
];

/** Switch between the three workflow workspaces (desktop header + mobile bar). */
function WorkspaceSwitcher({
  workspace,
  onChange,
  pending,
  className,
}: {
  workspace: Workspace;
  onChange: (w: Workspace) => void;
  pending: number;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-0.5 rounded border border-border p-0.5",
        className,
      )}
    >
      {WORKSPACES.map((w) => {
        // The act-surface (Decisions) lives in Terminal; surface a pending dot
        // there so an approval raised while in Discover/Review still pulls the
        // operator back.
        const showDot = w.id === "terminal" && pending > 0 && workspace !== "terminal";
        return (
          <button
            key={w.id}
            onClick={() => onChange(w.id)}
            aria-pressed={workspace === w.id}
            aria-label={showDot ? `${w.label}, ${pending} pending approval${pending !== 1 ? "s" : ""}` : undefined}
            className={cn(
              "relative flex-1 whitespace-nowrap rounded px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:py-1.5",
              workspace === w.id
                ? "bg-secondary text-foreground"
                : "text-muted-foreground/60 hover:text-muted-foreground",
            )}
          >
            {w.label}
            {showDot && (
              <span
                aria-hidden="true"
                className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-warning"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

function WatchlistButton({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title="Manage watchlist [W]"
      aria-keyshortcuts="w"
      aria-label={`Manage watchlist, ${count} instrument${count !== 1 ? "s" : ""}`}
      className="flex items-center gap-1.5 rounded border border-border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:border-muted-foreground/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-11 pointer-coarse:px-3 pointer-coarse:text-[11px]"
    >
      <ListChecks className="h-3.5 w-3.5" strokeWidth={1.75} />
      <span className="tabular-nums">{count}</span>
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
      className="grid shrink-0 border-t border-border bg-card pb-[env(safe-area-inset-bottom)]"
      style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}
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
        case "w":
        case "W":
          e.preventDefault();
          setWatchlistOpen((o) => !o);
          break;
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [handleHalt, handleModeChange]);

  const { ticks, handleEnvelope: handleTick } = useMarketTicks();
  const { snapshot } = usePortfolio();
  const { report, gates, handleEnvelope: handleCalibration } = useCalibration();
  const { report: analytics, handleEnvelope: handleAnalytics } = useAnalytics();
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
      handleAnalytics(envelope);
      handleWatchlist(envelope);
      handleFeedHealth(envelope);
    },
    [
      handleTick,
      handleSignal,
      handleThesis,
      handleDecision,
      handleCalibration,
      handleAnalytics,
      handleWatchlist,
      handleFeedHealth,
    ],
  );

  const { connected } = useEventStream(handleEnvelope);
  useBackfill(handleEnvelope);

  // ── Responsive shell ──────────────────────────────────────────────────────
  // The panels are grouped into three workflow workspaces (Discover/Terminal/
  // Review). Desktop renders the active workspace's multi-column layout; below
  // lg each workspace's panels become a bottom tab bar scoped to that workspace.
  // One branch renders at a time, so each panel mounts once.
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const [workspace, setWorkspace] = useState<Workspace>("terminal");
  const [activeTab, setActiveTab] = useState<TabId>("markets");
  const [watchlistOpen, setWatchlistOpen] = useState(false);

  // Switching workspace resets the mobile sub-tab to that workspace's first
  // panel (the bottom bar is scoped per workspace).
  const selectWorkspace = useCallback((w: Workspace) => {
    setWorkspace(w);
    setActiveTab(WORKSPACE_TABS[w][0]);
  }, []);

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
  const portfolio = <PortfolioPanel snapshot={snapshot} decisions={decisions} />;
  const calibration = <CalibrationPanel report={report} gates={gates} />;
  const analyticsPanel = <AnalyticsPanel report={analytics} />;
  const watchlistPanel = (
    <WatchlistPanel
      entries={watchlistEntries}
      loading={watchlistLoading}
      ticks={ticks}
      onAdd={watchlistAdd}
      onRemove={watchlistRemove}
    />
  );
  const discoveryFeed = <DiscoveryFeed onAdd={watchlistAdd} />;

  // Mobile bottom-bar tabs for the active workspace; the decisions badge is the
  // only dynamic bit.
  const workspaceTabs: TabDef[] = WORKSPACE_TABS[workspace].map((id) => ({
    id,
    label: TAB_META[id].label,
    icon: TAB_META[id].icon,
    badge: id === "decisions" ? pendingCount : undefined,
  }));

  const mobilePanel: Record<TabId, ReactNode> = {
    candidates: discoveryFeed,
    watchlist: watchlistPanel,
    markets: marketWatch,
    signals: signalFeed,
    theses: thesisFeed,
    decisions: decisionQueue,
    book: portfolio,
    calib: calibration,
    perf: analyticsPanel,
  };

  // DecisionQueue (the act-surface) mounts only in Terminal — on desktop the
  // whole workspace, on mobile its tab. Everywhere else a shell-level live
  // region keeps pending approvals audible.
  const decisionsMounted = isDesktop
    ? workspace === "terminal"
    : workspace === "terminal" && activeTab === "decisions";

  return (
    <div className="flex h-[100dvh] w-full flex-col bg-background text-foreground pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
      <header
        className="terminal-header flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] sm:px-4"
        data-mode={mode}
      >
        <span className="brand-logo order-1 text-xs font-semibold tracking-[0.25em] text-muted-foreground">
          AFTERHOURS
        </span>
        {isDesktop && (
          <div className="order-1">
            <WorkspaceSwitcher
              workspace={workspace}
              onChange={selectWorkspace}
              pending={pendingCount}
            />
          </div>
        )}
        {/* Controls: own full-width row on phones, inline on the right at sm+. */}
        <div className="order-3 flex w-full items-center justify-between gap-2 sm:order-2 sm:ml-auto sm:w-auto sm:justify-end sm:gap-3">
          <ModeIndicator mode={mode} onChange={handleModeChange} />
          <div className="flex items-center gap-2 sm:gap-3">
            <WatchlistButton
              count={watchlistEntries.length}
              onClick={() => setWatchlistOpen(true)}
            />
            <HaltButton onHalt={handleHalt} pulsing={mode === "assisted"} />
          </div>
        </div>
        <div className="order-2 ml-auto flex items-center gap-2 sm:order-3 sm:ml-0 sm:gap-3">
          <MarketClock />
          <ConnectionPip connected={connected} />
        </div>
      </header>

      <FeedHealthBar feeds={feedHealth} />

      {/* DecisionQueue carries its own live region while mounted; this covers
          pending approvals while the operator is in a workspace/tab without it. */}
      {!decisionsMounted && (
        <span className="sr-only" aria-live="assertive" aria-atomic="true">
          {pendingCount > 0
            ? `${pendingCount} decision${pendingCount !== 1 ? "s" : ""} pending approval`
            : ""}
        </span>
      )}

      {isDesktop ? (
        workspace === "terminal" ? (
          // Live operation: the flow scrolls on the left, the Decision Queue is
          // pinned as a rail on the right so the act-surface never scrolls away.
          <main className="flex min-h-0 flex-1 gap-2 overflow-hidden p-3">
            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
              <MarketWatch ticks={ticks} collapsible />
              <SignalFeed signals={signals} collapsible />
              <ThesisFeed theses={theses} collapsible />
            </div>
            <aside className="flex w-[22rem] shrink-0 flex-col overflow-y-auto xl:w-[26rem]">
              {decisionQueue}
            </aside>
          </main>
        ) : workspace === "review" ? (
          // Review: portfolio standing + calibration + performance, read between
          // sessions.
          <main className="min-h-0 flex-1 overflow-y-auto p-3">
            <div className="mx-auto grid max-w-5xl grid-cols-1 gap-2 xl:grid-cols-2">
              {portfolio}
              {calibration}
              <div className="xl:col-span-2">{analyticsPanel}</div>
            </div>
          </main>
        ) : (
          // Discover: the pre-watchlist funnel — candidate feed (Phase 6B) with
          // the watchlist as the curation rail.
          <main className="flex min-h-0 flex-1 gap-2 overflow-hidden p-3">
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto pr-1">
              {discoveryFeed}
            </div>
            <aside className="flex w-[22rem] shrink-0 flex-col overflow-y-auto xl:w-[26rem]">
              {watchlistPanel}
            </aside>
          </main>
        )
      ) : (
        <>
          <WorkspaceSwitcher
            workspace={workspace}
            onChange={selectWorkspace}
            pending={pendingCount}
            className="mx-2 mt-2"
          />
          {/* key resets scroll position and replays the enter fade per tab. */}
          <main
            key={activeTab}
            className="tab-panel flex-1 overflow-auto p-2"
          >
            {mobilePanel[activeTab]}
          </main>
          <MobileTabBar tabs={workspaceTabs} active={activeTab} onChange={setActiveTab} />
        </>
      )}

      <WatchlistDrawer
        open={watchlistOpen}
        onOpenChange={setWatchlistOpen}
        entries={watchlistEntries}
        loading={watchlistLoading}
        ticks={ticks}
        onAdd={watchlistAdd}
        onRemove={watchlistRemove}
      />
    </div>
  );
}
