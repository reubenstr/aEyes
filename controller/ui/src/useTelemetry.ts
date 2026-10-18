import { useEffect, useState } from 'react';
import { decodeTelemetry, reconnectDelay } from './data';
import type { Telemetry } from './types';

export function useTelemetry() {
  const [state, setState] = useState<Telemetry | null>(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    let disposed = false, attempt = 0, lastMessage = 0;
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout>;
    function connect() {
      if (disposed) return;
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`);
      socket.onmessage = event => {
        try {
          setState(decodeTelemetry(event.data)); setConnected(true);
          attempt = 0; lastMessage = Date.now();
        } catch { socket?.close(); }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (disposed) return;
        setConnected(false); setState(null); retry = setTimeout(connect, reconnectDelay(attempt++));
      };
    }
    connect();
    const watchdog = setInterval(() => {
      if (lastMessage && Date.now() - lastMessage > 2000) { setConnected(false); socket?.close(); }
    }, 1000);
    return () => { disposed = true; clearTimeout(retry); clearInterval(watchdog); socket?.close(); };
  }, []);
  return { state, connected };
}
