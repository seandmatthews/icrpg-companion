# 43 — session_reset semantics: version monotonicity, room code rotation

**Status:** completed — implemented and code-reviewed 2026-10-06.
**Priority:** P3
**Area:** `server/actions.py` (session_reset), `server/state.py`
(new_state), `server/hub.py` (commit)
**Found by:** 2026-10-06 full adversarial review

## Problem

1. **`version` goes backwards.** `session_reset` replaces state with
   `new_state(...)` (`actions.py:345-349`), whose version is 1
   (`state.py:44`); the next `Room.commit` writes 2 where the pre-reset
   version might have been 412 (`hub.py:31-34`). Harmless today only
   because the client never checks `state.version` — but ticket 32's
   own proposed client-side version check would misbehave after every
   reset, and any snapshot-vs-memory comparison inherits the trap.
2. **The room code cannot be rotated.** `session_reset` preserves
   `room_code` (that's `test_session_reset_keeps_room_identity`), so a
   code that leaked (photo of the QR shared, ex-player) survives
   "New session" forever. Contrast `--fresh`, which mints a new code.

## Proposal

- Carry the version counter across the reset: `new_version =
  state["version"] + 1` applied to the fresh state before install (or
  track a separate `(generation, version)` pair — pick one shape).
- Room code: ruled — see Ruling below (keep; no rotation work in this
  ticket).

## Ruling (do not revisit)

Room-code rotation on `session_reset` (2026-10-06): **keep the code.**
Mid-session reset is exactly when every device already holds the join
URL; rotating strands the printed/projected QR and forces a re-scan of
every phone. With the code kept, the reset flow is: state wipes,
players automatically re-knock (ticket 37), GM re-approves. The
residual risk — a leaked code surviving resets — only exposes the
knock gate (see ticket 38's ruling), which the GM sees and rejects.
`--fresh` already mints a new code for the genuinely-new-room case.

## Acceptance criteria

- [ ] `tests/test_actions.py::test_version_monotonic_across_reset` —
      drive a state to version N (N > 5), run `session_reset`, commit
      → `state["version"] > N`.
- [ ] `tests/test_actions.py::test_session_reset_preserves_room_identity`
      — amend the existing test to assert the code is kept explicitly
      (per the ruling) so the accepted residual risk is pinned, not
      accidental.

## Implementation notes (2026-10-06)

Landed in `server/actions.py` (session_reset) and `tests/test_actions.py`:

- Reset carries the version counter (`fresh["version"] = state["version"]`);
  the post-reset commit exceeds it, so version is strictly monotonic across a
  reset — ticket 32's proposed client staleness check can never see a
  collapse. Pinned by `test_version_monotonic_across_reset` (version bumps
  live in Room.commit, so the state-layer test drives a realistic counter
  directly).
- Room code kept per the Ruling; `test_session_reset_keeps_room_identity`
  now pins the carried version explicitly and documents the ruling (the old
  `version == 1` assertion was pinning the collapse — the bug). Note: the AC
  named the test `..._preserves_...`; the actual name is `..._keeps_...`
  (pre-existing).
- `--fresh` still mints version 1 (genuinely new room, no clients).
- Gates: `python -m pytest` — 102 passed ×2.
