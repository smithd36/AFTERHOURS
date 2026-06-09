import { useCallback, useEffect, useState } from "react";

export interface PositionSnapshot {
  side: "long" | "short";
  entry_price: string;
  current_price: string;
  quantity: string;
  size_usd: string;
  unrealized_pnl: string;
  stop_price: string | null;
  decision_id: string;
}

export interface PortfolioSnapshot {
  cash: string;
  total_value: string;
  unrealized_pnl: string;
  daily_realized_pnl: string;
  open_positions: number;
  positions: Record<string, PositionSnapshot>;
}

const POLL_INTERVAL_MS = 2000;

export function usePortfolio(): {
  snapshot: PortfolioSnapshot | null;
  refresh: () => void;
} {
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);

  const refresh = useCallback(() => {
    fetch("/api/portfolio")
      .then((r) => r.json())
      .then((data: PortfolioSnapshot) => setSnapshot(data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { snapshot, refresh };
}
