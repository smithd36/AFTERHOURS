import { useCallback, useReducer } from "react";
import type { EventEnvelope } from "@/types/core";

interface MarketTickPayload {
  instrument: string;
  venue?: string;
  price: string;
  best_bid?: string;
  best_ask?: string;
  volume_24h?: string;
  low_24h?: string;
  high_24h?: string;
  price_change_pct_24h?: string;
}

export interface TickRow {
  instrument: string;
  price: string;
  bestBid: string | null;
  bestAsk: string | null;
  volume24h: string | null;
  priceChangePct24h: string | null;
  lastUpdated: number;
}

type TickState = Record<string, TickRow>;

type Action =
  | { type: "tick"; payload: MarketTickPayload }
  | { type: "remove_instrument"; instrument: string };

function reducer(state: TickState, action: Action): TickState {
  if (action.type === "tick") {
    const p = action.payload;
    if (!p.instrument) return state;
    return {
      ...state,
      [p.instrument]: {
        instrument: p.instrument,
        price: p.price,
        bestBid: p.best_bid ?? null,
        bestAsk: p.best_ask ?? null,
        volume24h: p.volume_24h ?? null,
        priceChangePct24h: p.price_change_pct_24h ?? null,
        lastUpdated: Date.now(),
      },
    };
  }
  if (action.type === "remove_instrument") {
    if (!(action.instrument in state)) return state;
    const next = { ...state };
    delete next[action.instrument];
    return next;
  }
  return state;
}

export function useMarketTicks(): {
  ticks: TickState;
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [ticks, dispatch] = useReducer(reducer, {});

  const handleEnvelope = useCallback((envelope: EventEnvelope) => {
    if (envelope.event_type === "market.tick") {
      dispatch({ type: "tick", payload: envelope.payload as unknown as MarketTickPayload });
    } else if (envelope.event_type === "watchlist.instrument_removed") {
      const p = envelope.payload as Record<string, unknown>;
      dispatch({ type: "remove_instrument", instrument: String(p.instrument ?? "") });
    }
  }, []);

  return { ticks, handleEnvelope };
}
