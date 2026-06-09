import { useEffect, useRef, useState } from "react";
import type { EventEnvelope } from "@/types/core";

export function useEventStream(
  onMessage: (envelope: EventEnvelope) => void,
): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  // Ref keeps the handler stable — no reconnect needed when the callback changes.
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    let activeSocket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let mounted = true;
    let delay = 1_000;

    function connect() {
      if (!mounted) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${proto}//${window.location.host}/ws`);
      activeSocket = socket;

      socket.onopen = () => {
        if (!mounted) { socket.close(); return; }
        delay = 1_000;
        setConnected(true);
      };

      socket.onmessage = (evt) => {
        if (!mounted) return;
        try {
          onMessageRef.current(JSON.parse(evt.data) as EventEnvelope);
        } catch {
          // malformed frame — drop silently
        }
      };

      socket.onclose = () => {
        if (!mounted) return;
        setConnected(false);
        reconnectTimer = setTimeout(() => {
          delay = Math.min(delay * 2, 30_000);
          connect();
        }, delay);
      };

      socket.onerror = () => socket.close();
    }

    connect();

    return () => {
      mounted = false;
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      activeSocket?.close();
    };
  }, []); // single mount — handler changes handled via ref

  return { connected };
}
