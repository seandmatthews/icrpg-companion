# 42 — timer state machine consistency

**Status:** proposed
**Priority:** P3
**Area:** `server/actions.py` (timer handlers), `server/state.py`
(check_timers alarm slot), `client/src/components/Timers.tsx` (urgency)
**Found by:** 2026-10-06 full adversarial review

## Problem

Six inconsistencies in the timer handlers, all found by tracing every
branch:

1. **`timer_update` blank label empties the timer name.**
   `t["label"] = st.sanitize_name(str(args["label"]), 60)`
   (`actions.py:108`) has no `or t["label"]` fallback — unlike every
   sibling update handler (`:190, 228, 276`). `{label: "  "}` renders
   a nameless timer everywhere.
2. **Editing a done rounds timer leaves its alarm ringing.** The
   rounds branch (`actions.py:118-124`) resets status but never
   touches `state["alarm"]` — `timer_reset` clears it (`:158-159`).
   GM gives a rung-out timer more rounds → timer idle, but the "⏰ —
   TIME!" banner and every player's full-screen overlay persist until
   a separate `alarm_dismiss`.
3. **`timer_start` on a done alarm leaves the old alarm set**
   (`actions.py:132-142`) — same inconsistency: "start it again for 10
   more minutes" restarts the timer under a still-ringing banner.
4. **`timer_update` silently ignores kind-mismatched fields** —
   `{"rounds": 5}` on an alarm timer is a confusing successful no-op —
   and coerces looser than `timer_add` (`int("12")`, `int(10.5)` pass
   where `timer_add` requires real ints) (`actions.py:109-124`).
5. **`timer_pause`/`timer_tick` skip `_need_timer`** (`actions.py:144-149,
   161-164`): a typo'd id on pause reports "timer is not running" —
   misleading feedback while debugging a stale client.
6. **The alarm slot is single-use.** `check_timers` overwrites
   `state["alarm"]` per expiry (`state.py:159-171`): two timers
   expiring in the same watcher tick → both marked done, only the
   last rings; the earlier alarm silently never appears. (Window is
   one watcher tick — rare but silent when it hits.)
7. **Wall-clock stance is undocumented.** Deadlines are epoch-based
   (`state.py:33-34, 165`) — necessary for snapshot restore, but a
   backward NTP/manual clock step mid-session silently stretches
   every running alarm. DESIGN.md §10 should record the tradeoff;
   optionally detect backward steps and clamp.

## Proposal

- Mirror `timer_reset`'s alarm-clearing block in the `timer_update`
  rounds branch and in `timer_start` when the alarm references this
  timer.
- Add the `or t["label"]` fallback; reject kind-mismatched fields with
  an ActionError; align coercion strictness with `timer_add`.
- Route `timer_pause`/`timer_tick` through `_need_timer` first.
- Queue alarms: `state["alarm"]` becomes a list (or ring oldest and
  log swallowed expiries visibly) — pick one, pin it in tests.
- Record the wall-clock decision in DESIGN.md — ruled, see below.

## Ruling (do not revisit)

Wall-clock deadlines and backward clock steps (2026-10-06):
**document and accept.** Wall clock stays (snapshot restore requires
it); DESIGN.md §10 records the tradeoff — a backward step makes
alarms late, a forward step rings early, midnight/DST are non-events.
The failure direction is the benign one (late, never early), and
backward steps on a table laptop are rare. Detect-and-compensate
(`last_seen_now` + shifting `started_at` on a backward jump, pinned
by `test_backward_clock_step`) is the named fix if it ever bites at a
real table — its own ticket, not part of this one.

## Acceptance criteria

- [ ] `tests/test_actions.py::test_timer_update_clears_ringing_alarm` —
      run a rounds timer to done (alarm set), `timer_update {rounds: 5}`
      → `state["alarm"]` cleared; same assertion for `timer_start` on
      a done alarm timer.
- [ ] `tests/test_actions.py::test_timer_update_blank_label_keeps_label`
      — `{label: "  "}` leaves the previous label.
- [ ] `tests/test_actions.py::test_timer_update_wrong_kind_field_rejected`
      — `timer_update {timer_id, rounds: 5}` on an alarm timer raises
      ActionError; `duration_s: "12"` / `10.5` raise like `timer_add`.
- [ ] `tests/test_actions.py::test_pause_unknown_timer_says_no_such_timer`
      — pause/tick with a nonexistent id → "no such timer" wording.
- [ ] `tests/test_actions.py::test_two_alarms_same_tick_both_surface` —
      monkeypatched clock, two alarms with the same deadline, run
      `check_timers` → both surface (both in the alarm queue, or one
      rings and the swallow is a visible log entry — pin whichever).
- [ ] `tests/test_ws_flow.py::test_alarm_rings_without_client_action` —
      the coverage gap this suite has today: add a 2-second alarm over
      WS, then `recv()` on the GM *and* a player socket with **no
      further action sent**; both receive a state with `alarm` set.
      This is the only test that exercises the watcher end to end —
      the one path ticket 32 suspects can silently die.
- [ ] DESIGN.md §10 carries the wall-clock paragraph per the ruling
      (deliberate tradeoff; backward = late, forward = early;
      detect-and-compensate named as the follow-up if it ever
      matters).
