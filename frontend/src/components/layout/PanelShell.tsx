import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface PanelShellProps {
  title: string;
  rightSlot?: ReactNode;
  children: ReactNode;
  className?: string;
  /** When set, the header becomes a toggle that folds the body away. */
  collapsible?: boolean;
  defaultCollapsed?: boolean;
}

export function PanelShell({
  title,
  rightSlot,
  children,
  className,
  collapsible = false,
  defaultCollapsed = false,
}: PanelShellProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const open = !collapsible || !collapsed;

  const titleEl = (
    <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
      {title}
    </h2>
  );

  return (
    <div className={cn("rounded-sm border border-border bg-card", className)}>
      {collapsible ? (
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-expanded={open}
          className={cn(
            "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left transition-colors hover:bg-muted/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
            open && "border-b border-border",
          )}
        >
          <span className="flex items-center gap-1.5">
            <ChevronDown
              aria-hidden="true"
              className={cn(
                "h-3.5 w-3.5 text-muted-foreground/50 transition-transform duration-200",
                !open && "-rotate-90",
              )}
            />
            {titleEl}
          </span>
          {rightSlot != null && (
            <span className="text-[11px] text-muted-foreground">{rightSlot}</span>
          )}
        </button>
      ) : (
        <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
          {titleEl}
          {rightSlot != null && (
            <span aria-live="polite" aria-atomic="true" className="text-[11px] text-muted-foreground">
              {rightSlot}
            </span>
          )}
        </div>
      )}
      {open && children}
    </div>
  );
}
