import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { WatchlistPanel } from "@/components/panels/WatchlistPanel";
import type { WatchlistEntry } from "@/hooks/useWatchlist";

interface WatchlistDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entries: WatchlistEntry[];
  loading: boolean;
  ticks: Record<string, unknown>;
  onAdd: (instrument: string, market: "crypto" | "equity") => Promise<void>;
  onRemove: (instrument: string) => Promise<void>;
}

/**
 * Watchlist as a right-edge drawer rather than a permanent panel. It's
 * configuration, not live data — it shouldn't compete with the feed for screen
 * space during a session. Radix Dialog gives focus-trap, Escape, and scroll
 * lock for free; the panel inside is the unchanged WatchlistPanel.
 */
export function WatchlistDrawer({ open, onOpenChange, ...panel }: WatchlistDrawerProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay fixed inset-0 z-30 bg-background/70 backdrop-blur-[2px]" />
        <Dialog.Content
          aria-describedby={undefined}
          className="drawer-content fixed inset-y-0 right-0 z-40 flex w-full max-w-sm flex-col border-l border-border bg-background shadow-2xl pr-[env(safe-area-inset-right)]"
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
            <Dialog.Title className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              Manage Watchlist
            </Dialog.Title>
            <Dialog.Close
              aria-label="Close watchlist"
              className="flex h-8 w-8 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:h-11 pointer-coarse:w-11"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-2 pb-[env(safe-area-inset-bottom)]">
            <WatchlistPanel {...panel} />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
