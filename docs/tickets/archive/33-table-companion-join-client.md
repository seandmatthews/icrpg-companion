# 33 — table-companion: join/reject lifecycle + client type honesty

**Status:** completed — implemented and code-reviewed 2026-10-06 (two review rounds); manual cross-browser cache check pending user verification.
**Priority:** P3 — separate repo (`table-companion/`), own commits
**Area:** `table-companion/server/actions.py` (reject_join), `server/hub.py`,
`client/src/types.ts`, `client/src/net.ts`, `client/src/util.ts`
**Found by:** 2026-10-02 full review P3-42, P3-44, P3-45

## Problem

1. **`reject_join` doesn't stick (P3-42).** Rejecting a knock drops the
   request and logs to the GM — but nothing is sent to the player (conn
   stays `pending`, UI shows "Knock knock… waiting for the GM" forever),
   and any reload re-hellos via the localStorage seat and silently
   re-appends the join request (`actions.py:315-320`, `app.py:109-119`,
   `hub.py:100-101`, `PlayerView.tsx:45-55`). The rejected player
   reappears in the GM's knock panel immediately.
2. **Knock list restored from a snapshot lingers after a restart
   (P3-44).** Knocks are committed the moment they happen; the only
   cleanup is a live disconnect (`app.py:151-153`). A crash/restart while
   someone is knocking leaves stale "X is knocking" entries until manually
   rejected (approving still works — the binding is created for the device
   token).
3. **TS types lie about the pending view (P3-45).** `StateView` declares
   `timers`/`targets`/`alarm` required (`types.ts:63-81`) but the server's
   `_pending_view` omits them (`state.py:204-215`). Guarded today by the
   `status === "pending"` early-return — but the compiler can't catch a
   future violation; same class as the drift types exist to prevent.
4. **The localStorage view cache is not scoped (P3-45, cache half).** One key
   (`tc_view`, `util.ts:50-65`) serves GM and player flows across rooms
   and sessions; only cleared on auth failure. GM console + player PWA in
   one browser, or a `--fresh` restart mid-reconnect, briefly paints the
   wrong view (wrong-role "your seat vanished" flash).

## Proposal

- Send the rejected player a message (they render "the GM turned you
   away" and clear the saved seat); record the rejection (device-token
  list with TTL or until room reset) so a reload doesn't re-knock.
- On boot (state load), prune join requests whose conns are gone —
  stale knocks age out; keep committed knocks that arrive after boot.
- Make the pending view's omitted fields optional in `StateView` (or a
  discriminated union on `status`) so the compiler enforces the guard.
- Scope the cache key by room code + role (or drop the instant-paint
  cache for the pending status).

## Acceptance criteria

- [x] Rejected player sees the refusal and, after reload, does NOT
      reappear in the knock panel (test).
- [x] Restart with a snapshotted knock from a gone client: no ghost entry
      after boot (test).
- [x] `types.ts` compiles the guard: accessing `view.timers` without the
      status check is a type error (or equivalent union narrowing).
- [ ] GM-then-player in one browser paints no wrong-role flash (manual or
      DOM test).

## Related

The 2026-10-06 full review found two sibling defects outside this
ticket's triggers: `pc_delete`/`session_reset` orphan connected
players into a knockless pending limbo (no join request is created on
the demotion transition), and a two-tab device loses its live knock
when either tab closes — both in ticket 37, same fix surface
(`refresh_seats` / the ws `finally`).

## Implementation notes (2026-10-06)

Landed across `server/{state,actions,hub,app}.py`, `client/src/{types,net,util}.ts`,
`client/src/views/{PlayerView,GMView}.tsx`, and the test files:

- Rejection record: `state["rejections"]` holds `{"device_token", "name"}`
  (name kept so the GM console can offer re-seating). reject_join records it
  (and refuses to reject an already-seated device); approve_join clears it;
  session_reset wipes it; snapshot normalization restores it. A rejected
  device's hello is silent — no knock, no GM broadcast.
- Player notification: reject_join sends the rejected socket its rejected
  pending view (`rejected: true`) under the send lock
  (`Room.notify_rejection`), then closes it with **4003**; the client's
  onclose maps 4003 to the auth-fail path — saved seat cleared, no reconnect
  — while the "Turned away" screen stays painted (ticket's UX verbatim).
- Boot prune: `Room.__init__` clears snapshotted join_requests — knocks are
  live-session state, ghosts can never linger (AC2).
- Client types: `StateView` is now a discriminated union
  (`PendingView | ActiveView`) and `RoomConn` is generic over role, so the
  GM's view is typed as the full view it always receives and the compiler
  enforces the pending guard in PlayerView (AC3; build green).
- Cache scoping (AC4): per-role keys `tc_view_gm` / `tc_view_player`, plus a
  player-side room match before instant-paint. Known residual (documented):
  the GM's cache can still briefly paint a stale room — full fix rides
  tickets 40/41.
- Deviations from the proposal: no TTL on rejections — a rejection stands
  until the GM seats the person or the session resets; the GM console gained
  a "was turned away … seat anyway…" panel because the server override path
  would otherwise be unreachable (review round 1 flagged the promise/reality
  gap). hello_player now only broadcasts to GMs when a NEW knock was created
  (a rejected re-hello is silent — also fixes duplicate-knock broadcast noise).
- Two review rounds; round 1 flagged the unreachable override, the
  bound-token poisoning, and the unlock ordering — all fixed.
- Gates: `python -m pytest` — 69 passed; `npm run build` green. AC4's
  same-browser manual check left unticked pending user verification.
