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

function reducer(state: TickState, payload: MarketTickPayload): TickState {
  if (!payload.instrument) return state;
  return {
    ...state,
    [payload.instrument]: {
      instrument: payload.instrument,
      price: payload.price,
      bestBid: payload.best_bid ?? null,
      bestAsk: payload.best_ask ?? null,
      volume24h: payload.volume_24h ?? null,
      priceChangePct24h: payload.price_change_pct_24h ?? null,
      lastUpdated: Date.now(),
    },
  };
}

export function useMarketTicks(): {
  ticks: TickState;
  handleEnvelope: (envelope: EventEnvelope) => void;
} {
  const [ticks, dispatch] = useReducer(reducer, {});

  const handleEnvelope = useCallback((envelope: EventEnvelope) => {
    if (envelope.event_type === "market.tick") {
      dispatch(envelope.payload as MarketTickPayload);
    }
  }, []);

  return { ticks, handleEnvelope };
}
