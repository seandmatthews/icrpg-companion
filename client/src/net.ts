import { useCallback, useEffect, useRef, useState } from "react";
import type { StateView } from "./types";
import { cacheView, cachedView, getDevice } from "./util";

type Role = "gm" | "player";
type ConnStatus = "connecting" | "open" | "closed";

export interface RoomConn {
  status: ConnStatus;
  view: StateView | null;
  error: { message: string; ts: number } | null;
  skew: number; // server_time - local_time (seconds)
  send: (action: string, args?: Record<string, unknown>) => void;
}

/**
 * One WebSocket, hello on open, full-state on every message. Reconnect with
 * backoff; every reconnect re-sends hello and gets a full fresh state, which
 * is the whole sync model. The latest view is also mirrored to localStorage
 * so a reload paints instantly from cache before the server answers.
 */
export function useRoom(role: Role, opts: { room?: string; name?: string; gmKey?: string; onAuthFail?: () => void }): RoomConn {
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const [view, setView] = useState<StateView | null>(() => (cachedView() as StateView) ?? null);
  const [error, setError] = useState<{ message: string; ts: number } | null>(null);
  const [skew, setSkew] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const retryMs = useRef(1000);
  const onAuthFail = useRef(opts.onAuthFail);
  onAuthFail.current = opts.onAuthFail;

  const { room, name, gmKey } = opts;

  useEffect(() => {
    let closedByUs = false;
    let retryTimer: number | undefined;
    let pingTimer: number | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("open");
        retryMs.current = 1000;
        const device = getDevice();
        if (role === "gm") {
          ws.send(JSON.stringify({ type: "hello_gm", gm_token: gmKey ?? "", device_token: device }));
        } else {
          ws.send(JSON.stringify({ type: "hello_player", room: room ?? "", device_token: device, name: name ?? "Player" }));
        }
        pingTimer = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
        }, 25000);
      };

      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "state") {
          setSkew(msg.server_time - Date.now() / 1000);
          setView(msg.state);
          cacheView(msg.state);
        } else if (msg.type === "error") {
          setError({ message: msg.message, ts: Date.now() });
          if (msg.code === "auth") {
            closedByUs = true;
            ws.close();
            onAuthFail.current?.();
          }
        } else if (msg.type === "pong") {
          setSkew(msg.server_time - Date.now() / 1000);
        }
      };

      ws.onclose = () => {
        if (pingTimer) window.clearInterval(pingTimer);
        setStatus("closed");
        if (closedByUs) return; // auth failure: don't loop
        retryTimer = window.setTimeout(connect, retryMs.current);
        retryMs.current = Math.min(retryMs.current * 2, 5000);
      };
    };

    connect();
    return () => {
      closedByUs = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      if (pingTimer) window.clearInterval(pingTimer);
      wsRef.current?.close();
    };
  }, [role, room, name, gmKey]);

  const send = useCallback((action: string, args?: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "action", action, args: args ?? {} }));
    }
  }, []);

  return { status, view, error, skew, send };
}
