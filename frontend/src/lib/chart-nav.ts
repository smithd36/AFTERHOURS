import { createContext, useContext } from "react";

export interface ChartRequest {
  symbol: string;
  /** Bumps on every request so re-clicking the same symbol still re-triggers a load. */
  nonce: number;
}

interface ChartNav {
  request: ChartRequest | null;
  /** Open the Discover price chart for a symbol from anywhere in the app. */
  openChart: (symbol: string) => void;
}

export const ChartNavContext = createContext<ChartNav>({
  request: null,
  openChart: () => {},
});

export function useChartNav(): ChartNav {
  return useContext(ChartNavContext);
}
