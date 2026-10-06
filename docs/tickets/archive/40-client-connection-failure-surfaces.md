# 40 — client connection failure surfaces

**Status:** completed — implemented and code-reviewed 2026-10-06 (two review rounds); manual phone click-throughs pending user verification.
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

## Implementation notes (2026-10-06)

Landed in `client/src/net.ts`, `client/src/App.tsx`, 
`client/src/views/GMView.tsx`, `client/src/styles.css`:

- send() while the socket is down raises the toast ("reconnecting — try
  again in a moment") instead of vanishing; toasts auto-dismiss after 6 s
  (ts-guarded so a stale timer can't clear a newer error).
- Auth failure returns to the form WITH the reason: net.ts's onAuthFail now
  carries the server's message; GMFlow/PlayerFlow hold it in state (it
  survives the unmount that used to eat it) and the forms render it in red.
  A dead-server "Can't reach the table" card offers an explicit way back.
- Reconnect backoff is jittered ([0.5×, 1.5×]); the retry timer self-clears;
  visibilitychange probes an open socket / reconnects a closed one (never
  CONNECTING/CLOSING); garbled and non-object server frames warn-and-drop.
- Deviations (documented): the QR shows the origin-encoded URL during the
  bootstrap window rather than a "generating…" gate — disclosed by the
  modal's suspect warning (no lan_ip ⇒ suspect); the sub-millisecond
  onVisible/onclose double-connect race is left (self-corrects on the next
  hello).
- Two review rounds: round 1 caught that the wrong-key message was still
  never shown (the error died with the unmounted component) and that the
  blanket auth-fail reset had destroyed ticket 33's "Turned away" screen —
  the 4003 path no longer resets anything (comment documents the visibility-
  probe exception). Round 2 approved clean.
- Gates: `python -m pytest` — 90 passed; `npm run build` green. Manual
  click-through criteria left unticked pending user phone verification.
