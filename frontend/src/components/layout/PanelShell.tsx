import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PanelShellProps {
  title: string;
  rightSlot?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function PanelShell({
  title,
  rightSlot,
  children,
  className,
}: PanelShellProps) {
  return (
    <div className={cn("rounded-sm border border-border bg-card", className)}>
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          {title}
        </h2>
        {rightSlot != null && (
          <span aria-live="polite" aria-atomic="true" className="text-[11px] text-muted-foreground">
            {rightSlot}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
