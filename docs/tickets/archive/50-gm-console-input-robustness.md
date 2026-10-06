# 50 — GM console input robustness: double-taps, lost deltas, per-keystroke title

**Status:** completed — implemented and code-reviewed 2026-10-06 (two review rounds); manual phone click-throughs pending user verification.
**Priority:** P3, contained one P1-shaped item (Problem 1 — fixed)
**Area:** `client/src/views/GMView.tsx`,
`client/src/components/Timers.tsx` (GM forms), `server/actions.py`
(timer_tick, set_title, milestone_delete)
**Found by:** 2026-10-06 full adversarial review

## Problem

The GM console sends every input straight to `send()` with no
in-flight guard; on a touchscreen at the table this produces a family
of wrong outcomes:

1. **Double-tapping "Tick round" silently burns two rounds —
   irreversibly.** The Tick button is never disabled, including at
   `rounds_left === 0` (`Timers.tsx:70-74`), and each `timer_tick`
   decrements unconditionally while > 0 (`actions.py:161-170`);
   `timer_reset` only restores the *full* count (`actions.py:156-157`),
   so a lost round cannot be put back. The classic mobile accidental
   double-fire rings a room timer early or skips the intended tension
   beat with no trace and no undo.
2. **Double-taps on other controls raise spurious errors or duplicate
   work.** Pause ×2 → "timer is not running" toast
   (`actions.py:146-147`); Start/Resume ×2 → "already running";
   Recall ×2 → "already in the pool" (`:294-295`); approve ×2 → "no
   such join request"; starter-kit double-tap loads Alfheim twice
   (duplicate NPCs/loot, no bulk undo) (`GMView.tsx:356-358, 218-233,
   387-391`, `Timers.tsx:60-68`). Red toasts for normal double-taps
   train the GM to ignore the toast channel — which is also where
   real rejections arrive.
3. **Cancelling the milestone prompt still fires the action.**
   `prompt(...) ?? ""` sends `milestone_add` with an empty reason →
   guaranteed "missing 'reason'" toast (`GMView.tsx:320`).
4. **Form fields are cleared on send, not on success.** Add-timer and
   add-loot clear their inputs immediately (`GMView.tsx:52, 82`); if
   the send was dropped (socket down — ticket 40), the typed label is
   destroyed with nothing created.
5. **TN ± loses fast taps.** `set_targets` sends absolute values
   computed from the un-echoed view (`GMView.tsx:255`): two quick −
   taps both send `{default: 11}`; one decrement lands. Hearts
   correctly send deltas (`:332`); TN does not.
6. **Numeric inputs coerce garbage silently.** `min`/`max` attributes
   are decorative without JS validation: `""` → `+"" === 0`;
   `parseFloat("") || 1` maps an unparseable value to 1 heart
   (`"0"` is falsy → also 1) (`GMView.tsx:64, 66, 119, 130, 450`);
   out-of-range values surface as server toasts leaking arg names
   ("alarm needs duration_s (1..86400)").
7. **Index-keyed log and index-based milestone deletion.** Log renders
   with `key={i}` over a list the server trims from the front
   (`GMView.tsx:285-286`); milestones delete by array index
   (`GMView.tsx:397-400`, `actions.py:328-332`) — safe with one GM
   today, wrong-entry deletion under any future second writer or
   echo skew.
8. **The title input round-trips per keystroke.** Controlled by the
   server echo (`GMView.tsx:189-193`): every character is one action
   + commit + snapshot write + full broadcast (and a localStorage
   cache write), with visible echo-lag mangling on phone latency;
   and `set_title` rejects the empty string, so the title can never
   be cleared (`actions.py:79`).

## Proposal

- Per-button in-flight disable (or ~400 ms debounce) for all mutating
  GM controls; **disable Tick entirely while a tick is in flight and
  at `rounds_left === 0`** — the cheap UI fix for Problem 1 (a
  server-side idempotency key per tap is the alternative if the
  implementer prefers authority over UI guard).
- Milestone prompt: `const r = prompt(...); if (r?.trim()) send(...)`.
- Clear form fields only on the success echo.
- TN sends `{which, delta}` (server applies) or keep a local optimistic
  copy reconciled on echo.
- Client-side clamp/coerce with Add disabled on invalid values;
  server error messages reworded to not leak arg names.
- Server: milestones get stable ids (`milestone_delete` by id, log
  entries get ids); client keys by id.
- Title: local input state with debounce, commit on blur/Enter; server
  accepts an empty title (`sanitize_name` result of `""` allowed).

## Acceptance criteria

Server-side (pytest):

- [ ] `tests/test_actions.py::test_set_title_empty_allowed` —
      `set_title {title: ""}` → `state["title"] == ""` (no error);
      `{"title": "  "}` → `""` likewise.
- [ ] `tests/test_actions.py::test_milestone_delete_by_id` — add two
      milestones, delete the first by its id → the second is
      untouched (regression guard for the id switch); deleting a
      nonexistent id → ActionError.

Client-side (named manual click-throughs + build gate):

- [ ] Manual: with `rounds_left = 5`, double-tap Tick fast → exactly
      one decrement (second tap visibly blocked by the disabled
      state); at `rounds_left = 0` the Tick button is disabled.
- [ ] Manual: double-tap Pause/Start/Recall/approve fast → exactly one
      state change, no error toast for the second tap.
- [ ] Manual: starter kit with a double-tap → loaded exactly once.
- [ ] Manual: cancel the milestone prompt → no action sent, no toast.
- [ ] Manual: type a timer label, kill the server, submit → the label
      is still in the form (cleared only on success); restart, submit
      → created and form clears.
- [ ] Manual: tap TN − three times quickly → exactly three
      decrements (deltas, not absolutes).
- [ ] Manual: clear the title field and blur → title is empty on all
      clients; type a 30-char title → one commit (debounced), not
      thirty (observable via server log or snapshot mtime).
- [x] `npm run build` green.

## Implementation notes (2026-10-06)

Landed in `server/actions.py`, `server/state.py`, `client/src/types.ts`,
`client/src/views/GMView.tsx`, `client/src/components/Timers.tsx`, tests:

- The P1 Tick double-tap: TimerGM gains a `busy` prop — Tick is disabled
  while in flight AND at `rounds_left === 0`. GM console-wide: a single
  in-flight latch (`gsend`) wraps EVERY mutating control (timers, hearts,
  reveal/delete, loot assign/recall/delete, approve/reject, alarm dismiss,
  starter load, session reset, milestone, log note) — a send inside the echo
  window is ignored; the latch clears on any state frame or error frame.
  **Deviation:** the proposal's per-button disable landed as one latch
  (simpler, uniform); rapid legit taps inside one echo window are dropped
  rather than queued (deltas make that lossless at LAN latency).
- Server: `set_title` accepts the empty string (snapshot normalize no longer
  "repairs" an empty title back to the default); `set_targets` gained the
  delta shape `{which, delta}` (clamped 2..30; absolute shape retained);
  milestones carry stable `id`s and delete by id; log entries carry ids
  (normalize mints ids for pre-50 entries on load).
- Client: milestone prompt cancel/blank sends nothing; milestone list keyed
  and deleted by id; log keyed by id; TN card sends deltas (fast taps can no
  longer lose decrements); the four add-forms validate client-side (Add
  disabled on invalid), clear fields only on the success echo, and the
  title is a local draft committed on blur/Enter.
- Two review rounds: round 1 caught a units regression (alarm duration sent
  in minutes — would have rung 60× early), the missing milestone/TN client
  edits, and the stuck-latch path on a dropped send — all fixed; round 2
  approved clean.
- Gates: `python -m pytest` — 90 passed ×2; `npm run build` green. Manual
  click-through criteria left unticked pending user phone verification.
