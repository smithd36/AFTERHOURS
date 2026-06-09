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
        <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          {title}
        </span>
        {rightSlot != null && (
          <span className="text-[10px] text-muted-foreground">{rightSlot}</span>
        )}
      </div>
      {children}
    </div>
  );
}
