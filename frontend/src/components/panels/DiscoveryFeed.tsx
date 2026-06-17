import { Telescope } from "lucide-react";
import { PanelShell } from "@/components/layout/PanelShell";

/**
 * Placeholder for the Phase 6B Discovery candidate feed (ADR-012). The Discover
 * workspace ships ahead of the `discovery/` backend, so this empty state holds
 * the slot the ranked candidate list will fill via `useDiscovery` in 6B.1.
 */
export function DiscoveryFeed() {
  return (
    <PanelShell title="Discovery" className="flex h-full flex-col">
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
        <Telescope
          aria-hidden="true"
          className="h-8 w-8 text-muted-foreground/40"
          strokeWidth={1.5}
        />
        <div className="space-y-1">
          <p className="text-sm font-medium text-muted-foreground">No candidates yet</p>
          <p className="max-w-xs text-xs text-muted-foreground/60">
            Ranked opportunities fused from multiple weak signals will surface here in Phase 6B.
            For now, curate your universe with the watchlist.
          </p>
        </div>
      </div>
    </PanelShell>
  );
}
