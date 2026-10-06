# 32 — table-companion: hub robustness (watcher, frames, partial mutations)

**Status:** completed — implemented and code-reviewed 2026-10-06 (two review rounds).
**Priority:** P2 — separate repo (`table-companion/`), own commits
**Area:** `table-companion/server/hub.py`, `server/app.py`, `server/actions.py`,
`server/content.py`
**Found by:** 2026-10-02 full review P2-9, P3-40, P3-41, P3-43

## Problem

1. **The broadcast error path can kill the timer-watcher task (P2-9,
   suspected).** Two broadcasts can be in flight concurrently (a slow
   phone's `send_text` yields on drain); when a dead conn fails in both,
   the second `self.conns.remove(conn)` raises `ValueError` out of
   `broadcast()` (`hub.py:64-70`). `app.py:140` calls it outside the error
   guard, but the real victim is `_timer_watcher` (`app.py:155-161`) — no
   guard at all — whose task dies, silently stopping server-side alarm
   resolution (DESIGN.md §6's core authority) until a client action
   happens to run `check_timers`. Related: concurrent broadcasts are
   unserialized and the client never checks `state.version` (`net.ts:60-63`
   applies any arriving state).
2. **Non-dict JSON frames or wrong-typed args crash the WS handler
   (P3-40).** `"x"`, `[1]`, `null`, or `{"default": "12a"}` raise
   non-`ActionError` exceptions out of the loop (`app.py:91-95`,
   `actions.py:82`…) — the socket aborts with no error message to the
   client, contrary to the ActionError contract.
3. **Rejected `*_update` actions partially mutate state (P3-41).**
   Fields are mutated before later fields validate (`actions.py:187-198`
   pc_update, npc/loot/timer same); the caller catches `ActionError` and
   continues without commit/broadcast — the sender sees an error toast
   while their earlier fields live unbroadcast in memory until an
   unrelated action commits them under a wrong version bump.
4. **Malformed starter pack kills the GM's connection (P3-43).** Valid
   JSON with a missing `name`/`duration_s` raises `KeyError` through
   `apply_action` (`content.py:43-58`); only FileNotFoundError/
   JSONDecodeError become ActionError — plus entries appended before the
   crash sit uncommitted.

## Proposal

- `self.conns.discard(conn)` (or guard removal); wrap the watcher body in
  try/except with a warning log; serialize broadcasts per room (an
  asyncio.Lock or a single sender task) so full-state ordering is
  guaranteed; optionally stamp and check `state.version` client-side.
- Validate the frame shape (`isinstance(msg, dict)`) and coerce/validate
  args centrally (`_need` raising ActionError on non-int-coercible)
  before any handler runs.
- Make `*_update` handlers validate-all-then-mutate (collect changes,
  apply once) so a rejection leaves state untouched.
- Content packs: validate required keys/types per entry → ActionError
  naming the entry; apply only after full validation.

## Acceptance criteria

- [x] A deliberately stalled socket + overlapping broadcasts: watcher
      survives, alarms still resolve (test with a fake conn that raises).
- [x] Malformed frames return an error message to the client, socket
      stays open (test each wrong shape).
- [x] `pc_update {name, hearts_max: 99}` rejection leaves `name`
      uncommitted and unbroadcast (state-diff test).
- [x] A pack missing `name` → readable ActionError, no partial apply.

## Related

The 2026-10-06 full review split this ticket's scope: the *crash*
class stays here; the *silent-corruption* wrong-typed args (null →
`"None"`, string abilities, bool-as-int, truthy flags) moved to
ticket 36, and pack validation beyond the missing-key KeyError (tier,
sanitize, BOM) to ticket 48. Land 36's central field helpers as part
of this ticket's coercion proposal where they overlap.

## Implementation notes (2026-10-06)

Landed in `server/hub.py`, `server/app.py`, `server/actions.py`,
`server/content.py`, `tests/test_actions.py`, `tests/test_ws_flow.py`:

- Broadcast: a per-room `asyncio.Lock` serializes full-state frames
  (ordering guarantee) and `_drop()` (guarded remove) makes dead-conn
  reaping idempotent — two overlapping broadcasts can no longer raise
  ValueError out of `conns.remove`. The ws finally-block uses the same
  `_drop`, so there is exactly one removal path.
- Watcher: body wrapped in `except Exception` with a warning log;
  CancelledError still propagates (BaseException), so shutdown is intact.
  A failed broadcast leaves the idempotent expiry in memory — delivered by
  the next action's broadcast. Pinned by `test_watcher_survives_dead_conn`
  (FailingWS fake conn + alarm ringing with NO client action driving it —
  the first end-to-end watcher coverage in the suite).
- Frames: non-dict JSON frames and non-dict `args` get an error frame and
  stay connected; `_need_number`/`_finite_float` reject strings, bools,
  NaN/Infinity, and huge ints (`10**400` → OverflowError → ActionError) in
  hearts deltas and npc hearts; `set_targets`/`milestone_delete` intake via
  `_opt_int`. Pinned by `test_malformed_frames_get_errors_not_disconnects`
  and `test_wrong_typed_action_args_get_errors`.
- Partial mutations: all four `*_update` handlers validate everything
  (including ranges/tier/die) BEFORE the first mutation. Pinned by
  `test_rejected_update_leaves_state_untouched`.
- Content packs: `_validate_pack` validates the WHOLE pack (root object,
  per-entry shapes, tiers, kinds, ranges) before anything is appended —
  a malformed pack is a readable ActionError naming the entry, with zero
  partial apply. Pinned by `test_malformed_pack_fails_without_partial_apply`.
- Deliberately not done: the client-side `state.version` check (the ticket's
  optional 4th item) — server-side ordering is now guaranteed by the lock;
  the client check can ride a future client-lane ticket if wanted.
- Known accepted P3 (noted for a follow-up): the send lock is held across
  `await send_text`, so a client that stops reading (TCP window full) can
  delay the room's broadcasts until its socket errors out — a per-send
  `asyncio.wait_for` timeout or per-conn outbound queue is the fix if it
  ever shows at a real table.
- Review reuse: the arg-intake guards share ticket 36's helpers
  (`_opt_str`/`_opt_int`/`_opt_bool`); the pack tier/sanitize validation
  partially pre-empts ticket 48 (which keeps the BOM + field-bypass items).
- Two review rounds; round 1 caught the OverflowError escape (huge JSON
  ints) — fixed with `_finite_float` and probed live. Gates:
  `python -m pytest` — 67 passed (twice for flake check).
