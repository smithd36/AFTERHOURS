import { useCallback, useState } from "react";

export interface Bar {
  t: number; // epoch seconds (UTC)
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export type ChartRange = "1D" | "1W" | "1M" | "3M" | "1Y";

export interface ChartData {
  instrument: string;
  market: "crypto" | "equity";
  range: ChartRange;
  bars: Bar[];
}

// Pull-first, like useDiscovery: fetched on demand when the operator searches a
// symbol or changes range — no event stream, no auto-fetch on mount.
export function useChart(): {
  data: ChartData | null;
  loading: boolean;
  error: string | null;
  load: (symbol: string, range: ChartRange) => Promise<void>;
} {
  const [data, setData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (symbol: string, range: ChartRange) => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/chart/${encodeURIComponent(sym)}?range=${range}`);
      if (!r.ok) {
        const detail = await r.json().catch(() => null);
        throw new Error(detail?.detail ?? `HTTP ${r.status}`);
      }
      const json = (await r.json()) as ChartData;
      if (json.bars.length === 0) throw new Error(`no bars for ${sym}`);
      setData(json);
    } catch (e: unknown) {
      setData(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  return { data, loading, error, load };
}
