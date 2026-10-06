import { useCallback, useEffect, useRef, useState } from "react";
import type { ActiveView, StateView } from "./types";
import { cacheView, cachedView, getDevice } from "./util";

type Role = "gm" | "player";
type ConnStatus = "connecting" | "open" | "closed";

export interface RoomConn<R extends Role = Role> {
  status: ConnStatus;
  // the GM always receives a full view; a player may receive the pending one
  view: (R extends "gm" ? ActiveView : StateView) | null;
  error: { message: string; ts: number } | null;
  skew: number; // server_time - local_time (seconds)
  send: (action: string, args?: Record<string, unknown>) => void;
}

const TOAST_MS = 6000;

/**
 * One WebSocket, hello on open, full-state on every message. Reconnect with
 * jittered backoff; every reconnect re-sends hello and gets a full fresh
 * state, which is the whole sync model. The latest view is also mirrored to
 * localStorage (per role — ticket 33) so a reload paints instantly from cache
 * before the server answers.
 *
 * Failure surfaces (ticket 40): a send while the socket is down raises the
 * error toast instead of vanishing; toasts auto-dismiss; wakes from
 * backgrounding re-probe the socket immediately; a stale/garbled server
 * frame can never throw out of the handler.
 */
export function useRoom<R extends Role>(
  role: R,
  opts: { room?: string; name?: string; gmKey?: string; onAuthFail?: (message: string) => void }
): RoomConn<R> {
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const [view, setView] = useState<StateView | null>(() => {
    const cached = cachedView(role) as StateView | null;
    // a player's cache is only painted for the room they are joining
    if (role === "player" && opts.room && cached && cached.room_code !== opts.room) return null;
    return cached;
  });
  const [error, setError] = useState<{ message: string; ts: number } | null>(null);
  const [skew, setSkew] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const retryMs = useRef(1000);
  const onAuthFail = useRef(opts.onAuthFail);
  onAuthFail.current = opts.onAuthFail;

  const { room, name, gmKey } = opts;

  // the only error surface auto-dismisses: a stale "wrong room code" must
  // not stick on screen after the situation resolves (ticket 40)
  useEffect(() => {
    if (!error) return;
    const id = window.setTimeout(() => {
      setError((cur) => (cur && cur.ts === error.ts ? null : cur));
    }, TOAST_MS);
    return () => window.clearTimeout(id);
  }, [error]);

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
        let msg: unknown;
        try {
          msg = JSON.parse(typeof ev.data === "string" ? ev.data : "");
        } catch {
          console.warn("tc: dropped a garbled server frame");
          return; // a garbled frame is dropped, never fatal
        }
        if (!msg || typeof msg !== "object") {
          console.warn("tc: dropped a non-object server frame");
          return;
        }
        const m = msg as Record<string, unknown>;
        if (m.type === "state") {
          setSkew((m.server_time as number) - Date.now() / 1000);
          setView(m.state as StateView);
          cacheView(m.state, role);
        } else if (m.type === "error") {
          const message = String(m.message ?? "rejected");
          setError({ message, ts: Date.now() });
          if (m.code === "auth") {
            closedByUs = true;
            ws.close();
            onAuthFail.current?.(message); // the form must show WHY (ticket 40)
          }
        } else if (m.type === "pong") {
          setSkew((m.server_time as number) - Date.now() / 1000);
        }
      };

      ws.onclose = (ev) => {
        if (pingTimer) window.clearInterval(pingTimer);
        setStatus("closed");
        if (ev.code === 4003) {
          // the GM turned this knock away: no reconnect LOOP, no state reset —
          // the "Turned away" screen paints from the retained pending view and
          // the saved seat stays (the GM can still seat this device). The
          // visibility probe may still reconnect, which is fine: the server
          // answers a rejected device's re-hello with the same rejected view
          // and never re-knocks the GM (ticket 33)
          return;
        }
        if (closedByUs) return; // auth failure: don't loop
        // jittered backoff: 4-8 phones waking together must not all land in
        // the same instant (ticket 40)
        const jittered = retryMs.current * (0.5 + Math.random());
        retryTimer = window.setTimeout(() => {
          retryTimer = undefined;
          connect();
        }, jittered);
        retryMs.current = Math.min(retryMs.current * 2, 5000);
      };
    };

    connect();
    // a woken tab can sit on a dead socket with a green dot for tens of
    // seconds — probe the moment the user looks at it (ticket 40)
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      } else if ((!ws || ws.readyState === WebSocket.CLOSED) && !closedByUs && !retryTimer) {
        connect();
      }
      // CONNECTING/CLOSING sockets are already on their way somewhere
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      closedByUs = true;
      document.removeEventListener("visibilitychange", onVisible);
      if (retryTimer) window.clearTimeout(retryTimer);
      if (pingTimer) window.clearInterval(pingTimer);
      wsRef.current?.close();
    };
  }, [role, room, name, gmKey]);

  const send = useCallback((action: string, args?: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "action", action, args: args ?? {} }));
    } else {
      // a tap during a reconnect window is surfaced, never silently dropped
      // (ticket 40)
      setError({ message: "reconnecting — try again in a moment", ts: Date.now() });
    }
  }, []);

  return { status, view: view as RoomConn<R>["view"], error, skew, send };
}
