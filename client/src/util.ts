import { useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// local storage identity: the device token re-binds seats; the cached view is
// an instant-paint mirror only (see net.ts) — the server snapshot is the backup.
// ---------------------------------------------------------------------------

const DEVICE_KEY = "tc_device";
const GM_KEY = "tc_gmkey";
const SEAT_KEY = "tc_seat"; // {room, name}
// the instant-paint view cache is scoped per role — one browser can host the
// GM console and a player seat, and they must never cross-paint (ticket 33)
const VIEW_KEYS: Record<"gm" | "player", string> = { gm: "tc_view_gm", player: "tc_view_player" };

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
  try {
    return localStorage.getItem(GM_KEY);
  } catch {
    return null;
  }
}

export function setGmKey(k: string | null) {
  try {
    if (k) localStorage.setItem(GM_KEY, k);
    else localStorage.removeItem(GM_KEY);
  } catch {
    /* storage unavailable — the session just won't persist */
  }
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
  try {
    if (seat) localStorage.setItem(SEAT_KEY, JSON.stringify(seat));
    else localStorage.removeItem(SEAT_KEY);
  } catch {
    /* storage unavailable — the session just won't persist */
  }
}

export function cacheView(v: unknown, role: "gm" | "player") {
  try {
    localStorage.setItem(VIEW_KEYS[role], JSON.stringify(v));
  } catch {
    /* quota — the cache is a nicety, never fatal */
  }
}

// the cache is painted before the server answers, so its shape is validated:
// an old-build or hand-mangled blob must boot to a form, never throw on first
// paint (ticket 41)
function validCachedView(v: unknown, role: "gm" | "player"): boolean {
  if (!v || typeof v !== "object") return false;
  const r = v as Record<string, unknown>;
  if (
    r.schema !== "table-companion/v0" ||
    typeof r.version !== "number" ||
    typeof r.room_code !== "string" ||
    typeof r.title !== "string"
  ) {
    return false;
  }
  // pending-shaped blobs are legit for players and poison for the GM console,
  // and anything active-shaped must carry the fields the paint path indexes —
  // including the alarm queue (an old-build single-dict alarm would loop
  // "Tap to reload" forever). Otherwise: boot to a form, never throw.
  if (r.status === "pending") return role === "player" && Array.isArray(r.party);
  return (
    Array.isArray(r.timers) &&
    !!r.targets &&
    typeof r.targets === "object" &&
    typeof (r.targets as Record<string, unknown>).default === "number" &&
    typeof (r.targets as Record<string, unknown>).scene === "number" &&
    (r.alarm === null || Array.isArray(r.alarm))
  );
}

export function cachedView(role: "gm" | "player"): unknown | null {
  try {
    const raw = localStorage.getItem(VIEW_KEYS[role]);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!validCachedView(parsed, role)) {
      localStorage.removeItem(VIEW_KEYS[role]);
      return null;
    }
    return parsed;
  } catch {
    try {
      localStorage.removeItem(VIEW_KEYS[role]);
    } catch {
      /* storage itself is gone — nothing to clean */
    }
    return null;
  }
}

export function clearCachedView() {
  try {
    localStorage.removeItem(VIEW_KEYS.gm);
    localStorage.removeItem(VIEW_KEYS.player);
  } catch {
    /* nothing to clean */
  }
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
        const nav = navigator as Navigator & {
          wakeLock?: { request: (t: "screen") => Promise<{ release: () => Promise<void> }> };
        };
        if (nav.wakeLock && document.visibilityState === "visible") {
          const l = await nav.wakeLock.request("screen");
          if (cancelled) {
            l.release().catch(() => {});
            return;
          }
          lock = l;
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
  t: {
    kind: "alarm" | "rounds";
    status: string;
    started_at: number | null;
    duration_s: number | null;
    elapsed_before_pause?: number;
  },
  skew: number,
  now: number
): number | null {
  if (t.kind !== "alarm" || t.duration_s == null) return null;
  if (t.status === "running") {
    if (t.started_at == null) return null;
    return t.started_at + t.duration_s - (now + skew);
  }
  // honesty for the player view (ticket 39): a paused timer shows what's
  // actually left (frozen), a done timer shows 0:00 — never the full duration
  if (t.status === "paused") return t.duration_s - (t.elapsed_before_pause ?? 0);
  if (t.status === "done") return 0;
  return null; // idle
}
