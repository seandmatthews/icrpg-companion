# 40 — client connection failure surfaces

**Status:** proposed
**Priority:** P2
**Area:** `client/src/net.ts`, `client/src/App.tsx`, toast consumers
(`GMView.tsx:427-431`, `PlayerView.tsx:127-131`), `GMView.tsx` (QR)
**Found by:** 2026-10-06 full adversarial review

## Problem

Every way the client currently fails *silently* when the connection
is unhappy (found independently by two lanes where noted):

1. **Actions no-op when the socket is down.** `send()` drops frames
   when `readyState !== OPEN` (`net.ts:94-99`): during a reconnect
   window (backoff up to 5 s; common after phone sleep) every tap —
   Pause, Claim, damage — vanishes with zero feedback. Buttons stay
   live; nothing queues; nothing reports. The only cue is a 12px dot
   where `conn-connecting` and `conn-closed` are the same red
   (`styles.css:410-417`).
2. **Auth failure dead-ends the UI.** `onAuthFail` clears localStorage
   but not React state (`App.tsx:52-55`): a wrong GM key renders
   "connecting to the table…" forever — and the early `!view` return
   precedes the toast, so the "wrong GM key" message is never shown at
   all. A stale seat after `--fresh` freezes the old view; reload is
   the only recovery.
3. **Error toasts never dismiss.** `conn.error` is only overwritten by
   the next error, never cleared on success or reconnect
   (`GMView.tsx:427-431`, `PlayerView.tsx:127-131`) — "wrong room
   code" sticks on screen after the situation resolves.
4. **Failed bootstrap silently mis-encodes the QR.** The
   `/api/bootstrap` fetch has no `r.ok` check, no timeout
   (`App.tsx:12-14`); a 500 JSON body "succeeds", `lan_ip` reads
   undefined, and `playersUrl` falls back to `location.origin` — the
   GM's laptop address, i.e. the QR makes phones connect to
   themselves (`GMView.tsx:182-184`).
5. **Net robustness odds:** deterministic backoff with no jitter
   (`net.ts:80-81`) — every suspended phone wakes in one lockstep
   wave; no `visibilitychange` revalidation, so a woken tab can show a
   green dot over minutes-old data; `onmessage` `JSON.parse` is
   unguarded and non-dict frames fall through every branch silently
   (`net.ts:59-73`).

## Proposal

- `send()` when not OPEN → raise the existing error surface
  ("reconnecting — try again") via `conn.error`; give
  `conn-connecting` a distinct (non-red, animated) treatment from
  `conn-closed`.
- Lift auth failure into React state: `onAuthFail` clears the
  key/seat *state* so the forms remount; make the `!view` placeholder
  branch on `conn.status` ("closed — wrong key?").
- Auto-clear toasts after ~6 s (timestamp already present) or on the
  next successful state.
- Bootstrap: check `r.ok`, add an AbortController timeout, render
  "generating…" until a real bootstrap lands, warn when falling back
  to `location.origin`.
- Jitter the backoff (`retryMs * (0.5 + Math.random())`); on
  `visibilitychange → visible`, ping immediately or force reconnect
  when not open; guard `JSON.parse` + frame shape (count/log bad
  frames, never crash).

## Acceptance criteria

Browser-gated; the pinning checks are named manual click-throughs
plus the build gate:

- [ ] Manual: start a session, kill the server (Ctrl+C), tap Pause →
      a visible "reconnecting" surface appears (toast or disabled
      state), not silence; restart the server → the tap succeeds and
      the surface clears.
- [ ] Manual: connecting/closed dot states are visually distinguishable
      (color + shape/animation) in both views.
- [ ] Manual: paste a wrong GM key → the key form returns with the
      error visible (no infinite "connecting…"); join a dead room code
      after `--fresh` → the join form returns.
- [ ] Manual: trigger an error toast, then perform a successful action
      → the toast clears within seconds without a reload.
- [ ] Manual: with the server stopped, reload the GM console and open
      Show QR → the modal does not present a QR that encodes
      `localhost` (generating state or explicit error instead).
- [ ] Manual (jitter, optional to automate): restart the server with 4+
      phones joined → hellos are visibly staggered rather than one
      wave (server log timestamps).
- [ ] `npm run build` green.
