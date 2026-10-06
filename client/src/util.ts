import { useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// local storage identity: the device token re-binds seats; the cached view is
// an instant-paint mirror only (see net.ts) — the server snapshot is the backup.
// ---------------------------------------------------------------------------

const DEVICE_KEY = "tc_device";
const GM_KEY = "tc_gmkey";
const SEAT_KEY = "tc_seat"; // {room, name}
const VIEW_KEY = "tc_view";

// crypto.randomUUID exists only in secure contexts (https / localhost); the
// table serves plain http://<lan-ip>, so phones must take the getRandomValues
// path. Minting is a pure bytes→token function so it stays testable.
export function mintDeviceToken(getBytes: (n: number) => Uint8Array): string {
  const b = getBytes(16);
  b[6] = (b[6] & 0x0f) | 0x40; // uuid v4 bits
  b[8] = (b[8] & 0x3f) | 0x80; // RFC 4122 variant
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function randomBytes(n: number): Uint8Array {
  const b = new Uint8Array(n);
  const c = globalThis.crypto;
  if (c && typeof c.getRandomValues === "function") {
    c.getRandomValues(b);
  } else {
    // last-ditch: Math.random quality is irrelevant here — the token only
    // needs uniqueness, and this path must never throw (ticket 34)
    for (let i = 0; i < n; i++) b[i] = Math.floor(Math.random() * 256);
  }
  return b;
}

export function getDevice(): string {
  try {
    let d = localStorage.getItem(DEVICE_KEY);
    if (!d) {
      const c = crypto as Omit<Crypto, "randomUUID"> & { randomUUID?: () => string };
      d = c.randomUUID ? c.randomUUID() : mintDeviceToken(randomBytes);
      localStorage.setItem(DEVICE_KEY, d);
    }
    return d;
  } catch {
    // insecure context without getRandomValues, storage disabled, … — a
    // session-only token beats throwing inside ws.onopen (ticket 34)
    console.warn("tc: device identity unavailable, using a session-only token");
    return mintDeviceToken(randomBytes);
  }
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
