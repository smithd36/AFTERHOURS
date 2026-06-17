import { useCallback, useEffect, useState } from "react";

// The Discovery feed is a pull-first projection (ADR-012): there is no
// discovery.* event stream in the 6B.1 MVP, so this hook just fetches the
// ranked candidates from /api/discovery and exposes a manual refresh.

export interface DiscoveryContribution {
  factor: string;
  weight: number; // signed: + bullish, - bearish/risk
  age_days: number;
  summary: string;
  source: string;
}

export interface DiscoveryCandidate {
  instrument: string;
  score: number; // 0..1
  factors: string[];
  contributions: DiscoveryContribution[];
}

// AI analyst output (lazy, per-candidate; GET /api/discovery/{instrument}/analysis).
export interface DiscoveryAnalysis {
  instrument: string;
  thesis: string;
  risks: string[]; // counter-signals / bear case
  evidence_summary: string;
  suggested_step: string;
}

interface DiscoveryResponse {
  generated_at: string;
  candidates: DiscoveryCandidate[];
}

export function useDiscovery(): {
  candidates: DiscoveryCandidate[];
  loading: boolean;
  error: string | null;
  generatedAt: string | null;
  refresh: () => void;
} {
  const [candidates, setCandidates] = useState<DiscoveryCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    fetch("/api/discovery")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<DiscoveryResponse>;
      })
      .then((d) => {
        setCandidates(d.candidates);
        setGeneratedAt(d.generated_at);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { candidates, loading, error, generatedAt, refresh };
}
