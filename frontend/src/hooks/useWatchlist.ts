import { useCallback, useEffect, useReducer } from "react";
import type { EventEnvelope } from "@/types/core";

export interface WatchlistEntry {
  instrument: string;
  market: "crypto" | "equity";
  added_at: string; // ISO-8601 UTC
}

type State = {
  entries: WatchlistEntry[];
  loading: boolean;
  error: string | null;
};

type Action =
  | { type: "loaded"; entries: WatchlistEntry[] }
  | { type: "added"; entry: WatchlistEntry }
  | { type: "removed"; instrument: string }
  | { type: "error"; message: string };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "loaded":
      return { ...state, entries: action.entries, loading: false, error: null };
    case "added": {
      if (state.entries.some((e) => e.instrument === action.entry.instrument)) {
        return state;
      }
      return { ...state, entries: [...state.entries, action.entry] };
    }
    case "removed":
      return {
        ...state,
        entries: state.entries.filter((e) => e.instrument !== action.instrument),
      };
    case "error":
      return { ...state, loading: false, error: action.message };
    default:
      return state;
  }
}

const INITIAL: State = { entries: [], loading: true, error: null };

export function useWatchlist(): {
  entries: WatchlistEntry[];
  loading: boolean;
  error: string | null;
  add: (instrument: string, market: "crypto" | "equity") => Promise<void>;
  remove: (instrument: string) => Promise<void>;
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [state, dispatch] = useReducer(reducer, INITIAL);

  // Load snapshot on mount
  useEffect(() => {
    fetch("/api/watchlist")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ instruments: WatchlistEntry[] }>;
      })
      .then((d) => dispatch({ type: "loaded", entries: d.instruments }))
      .catch((e: unknown) =>
        dispatch({ type: "error", message: String(e) })
      );
  }, []);

  const add = useCallback(
    async (instrument: string, market: "crypto" | "equity") => {
      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instrument, market }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text);
      }
    },
    [],
  );

  const remove = useCallback(async (instrument: string) => {
    const res = await fetch(`/api/watchlist/${encodeURIComponent(instrument)}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text);
    }
  }, []);

  const handleEnvelope = useCallback((envelope: EventEnvelope) => {
    if (envelope.event_type === "watchlist.instrument_added") {
      const p = envelope.payload as Record<string, unknown>;
      dispatch({
        type: "added",
        entry: {
          instrument: String(p.instrument ?? ""),
          market: (p.market as "crypto" | "equity") ?? "crypto",
          added_at: envelope.event_time,
        },
      });
    } else if (envelope.event_type === "watchlist.instrument_removed") {
      const p = envelope.payload as Record<string, unknown>;
      dispatch({ type: "removed", instrument: String(p.instrument ?? "") });
    }
  }, []);

  return {
    entries: state.entries,
    loading: state.loading,
    error: state.error,
    add,
    remove,
    handleEnvelope,
  };
}
