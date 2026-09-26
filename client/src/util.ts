import { useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// local storage identity: the device token is what the server re-binds seats
// with; the cached view gives returning phones an instant paint and is purely
// a mirror — the server snapshot is the real backup.
// ---------------------------------------------------------------------------

const DEVICE_KEY = "tc_device";
const GM_KEY = "tc_gmkey";
const SEAT_KEY = "tc_seat"; // {room, name}
const VIEW_KEY = "tc_view";

export function getDevice(): string {
  let d = localStorage.getItem(DEVICE_KEY);
  if (!d) {
    d = crypto.randomUUID();
    localStorage.setItem(DEVICE_KEY, d);
  }
  return d;
}

export function getGmKey(): string | null {
  return localStorage.getItem(GM_KEY);
}

export function setGmKey(k: string | null) {
  if (k) localStorage.setItem(GM_KEY, k);
  else localStorage.removeItem(GM_KEY);
}

export interface Seat {
  room: string;
  name: string;
}

export function getSeat(): Seat | null {
  try {
    const raw = localStorage.getItem(SEAT_KEY);
    return raw ? (JSON.parse(raw) as Seat) : null;
  } catch {
    return null;
  }
}

export function setSeat(seat: Seat | null) {
  if (seat) localStorage.setItem(SEAT_KEY, JSON.stringify(seat));
  else localStorage.removeItem(SEAT_KEY);
}

export function cacheView(v: unknown) {
  try {
    localStorage.setItem(VIEW_KEY, JSON.stringify(v));
  } catch {
    /* quota — the cache is a nicety, never fatal */
  }
}

export function cachedView(): unknown | null {
  try {
    const raw = localStorage.getItem(VIEW_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearCachedView() {
  localStorage.removeItem(VIEW_KEY);
}

// ---------------------------------------------------------------------------
// hooks
// ---------------------------------------------------------------------------

/** Re-render every `ms` (default 500ms) so countdowns tick. */
export function useNow(ms = 500): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

/** Keep the screen awake while the table plays (timer + GM console). */
export function useWakeLock(active: boolean) {
  useEffect(() => {
    if (!active) return;
    let lock: { release: () => Promise<void> } | null = null;
    let cancelled = false;
    const acquire = async () => {
      try {
        const nav = navigator as Navigator & { wakeLock?: { request: (t: "screen") => Promise<typeof lock> } };
        if (nav.wakeLock && document.visibilityState === "visible") {
          lock = await nav.wakeLock.request("screen");
        }
      } catch {
        /* unsupported or denied — fine */
      }
    };
    const onVis = () => {
      if (document.visibilityState === "visible" && !lock && !cancelled) acquire();
    };
    acquire();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVis);
      lock?.release().catch(() => {});
    };
  }, [active]);
}

// ---------------------------------------------------------------------------
// time + timer math (server-clock corrected)
// ---------------------------------------------------------------------------

export function fmtClock(totalSeconds: number): string {
  const s = Math.max(0, Math.ceil(totalSeconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

export function timerRemainSec(
  t: { kind: "alarm" | "rounds"; status: string; started_at: number | null; duration_s: number | null },
  skew: number,
  now: number
): number | null {
  if (t.kind !== "alarm" || t.status !== "running" || t.started_at == null || t.duration_s == null) return null;
  return t.started_at + t.duration_s - (now + skew);
}

export function urlBase64Bytes(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const s = (b64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(s);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}
