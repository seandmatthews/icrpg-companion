# 46 — boot & commit robustness odds

**Status:** completed — implemented and code-reviewed 2026-10-06 (two review rounds).
**Priority:** P3
**Area:** `run.py`, `server/app.py` (create_app), `server/state.py`
(save_snapshot, clear_snapshot, id4), `server/hub.py` (commit, dumps)
**Found by:** 2026-10-06 full adversarial review

## Problem

Small-but-real robustness odds and ends in the boot/commit path:

1. **`--fresh` destroys the old session before it has a successor.**
   Order is: clear snapshot → load → banner → `uvicorn.run` binds
   (`run.py:28` → `app.py:53-54` → `run.py:53`). A double-launch
   (port taken) or Ctrl+C before the first action leaves the table
   with *neither* the old nor a new snapshot. `clear_snapshot`'s
   `os.remove` can itself raise `PermissionError` (file open in an
   editor) and crash boot with a traceback.
2. **A failing `save_snapshot` kills the committing client's socket.**
   `commit()` → `save_snapshot` runs inside the action loop, which
   catches only `ActionError` (`app.py:127-139`): a `PermissionError`
   from `os.replace` while an editor/AV holds `state.json` open (a
   realistic Windows scan window) escapes and tears down the acting
   client's connection — repeatedly, on every action, while the file
   stays locked.
3. **No lockfile.** Two `run.py` processes (e.g. different ports) both
   restore and both `os.replace` the same `data/state.json` —
   last-writer-wins split brain with two different room codes.
4. **`allow_nan=True` default.** `json.dump`/`json.dumps`
   (`state.py:248`, `hub.py:60`) happily write bare `NaN`, which every
   browser's `JSON.parse` rejects — one bad coercion would poison the
   snapshot and all clients while the server keeps "working".
5. **`id4` never checks uniqueness** (`state.py:25-26`): 48-bit ids,
   ~0.1% collision odds by n=200 objects in a long restored session;
   `find_*` returns the first match, so a collision silently
   misroutes claims/edits/deletes.
6. **Banner box breaks on long player URLs** (`run.py:41-45`) — the
   `│` drifts out of the box; cosmetic.

## Proposal

- Pre-check/bind the port before clearing (or defer deletion to the
  first commit); catch/handle the locked-file case in
  `clear_snapshot`.
- Guard the commit path: catch/log `OSError` (and `TypeError`) in
  `save_snapshot` so snapshot failure degrades to "session lives in
  memory" with a server-side warning; retry-once on replace.
- Exclusive lockfile in `data/` (`os.open(O_CREAT|O_EXCL)`, released
  on exit; stale-lock handling noted).
- `allow_nan=False` in both dump sites (fail loudly at the mutation).
- Mint-and-check loop in `new_item`/`new_timer`/`new_pc`/`new_npc`
  (regenerate while `find_*(state, id)` hits).
- Compute banner width from the longest row.

## Acceptance criteria

- [ ] `tests/test_persistence.py::test_fresh_bind_failure_preserves_snapshot`
      — write a valid snapshot; occupy the port with a raw socket;
      attempt boot with `fresh=True` → boot fails AND the old
      snapshot still loads afterwards (nothing deleted). Also: 
      `clear_snapshot` with the file locked (monkeypatch `os.remove`
      to raise PermissionError) → readable error, not a traceback.
- [ ] `tests/test_ws_flow.py::test_save_failure_does_not_kill_connection`
      — monkeypatch `os.replace` to raise once mid-session; the
      acting client's connection survives (next action works), a
      warning is logged, and snapshots resume after the mock is
      removed.
- [ ] `tests/test_app_boot.py::test_second_boot_refused_when_locked`
      (new file or test_ws_flow) — hold the lockfile; a second
      `create_app`/boot refuses with the lock message.
- [ ] `tests/test_persistence.py::test_non_finite_never_serialized` —
      inject `float("nan")` into a state dict and call
      `save_snapshot` → it raises loudly (never writes) rather than
      writing `NaN`; same expectation documented for the WS dump.
- [ ] `tests/test_actions.py::test_new_ids_unique_against_existing` —
      pre-seed state with 300 items minted via `new_item`; mint one
      more → no id in state collides (asserts the check loop; cheap
      because `find_*` is linear and the seed uses the same helper).
- [x] Banner: pinned by test_banner_frame_survives_long_urls instead of a manual check that the box
      renders with a long URL (or the width test is folded into a
      pure `banner_lines()` helper test if extracted).

## Implementation notes (2026-10-06)

Landed in `server/state.py`, `server/hub.py`, `server/app.py`, `run.py`,
`server/actions.py`, `tests/test_persistence.py`, `tests/test_ws_flow.py`:

- **--fresh defers deletion to the first commit** (Room.pending_clear): a
  bind failure or Ctrl+C before the first action leaves the old session on
  disk — the ticket's destructive double-launch scenario is now structural
  (nothing deletes before bind). clear_snapshot warns (not crashes) on a
  locked file; the subsequent save's os.replace hits the same lock and the
  commit guard degrades. Pinned by test_fresh_boot_defers_deletion_to_first_
  commit (the AC's literal port-occupancy step is subsumed: nothing deletes
  before bind) and test_clear_snapshot_locked_file_warns_not_crashes.
- **Commit guard**: hub.commit catches (OSError, TypeError, ValueError) →
  warning; the acting client keeps its connection; snapshots resume when the
  lock goes away. Pinned at BOTH layers: the state-level unit and the AC's
  named WS test (flaky os.replace fails exactly once; socket survives;
  resumes).
- allow_nan=False in BOTH dump sites (round 1 caught the WS dump was
  missed): save_snapshot raises loudly without writing; a NaN on the wire
  now fails that one conn loudly instead of silently poisoning every
  browser.
- Lockfile: data/.lock via O_EXCL with our pid; same-process re-boot reuses;
  a foreign-pid lock refuses with recovery instructions (stale-lock auto-
  detection is unreliable on Windows — deviation from the proposal's
  `os.kill` idea, disclosed in the error text). Released at atexit.
- id uniqueness: the four actions add-sites remint on collision (pinned by a
  300-item birthday seed). Deviations: content.load_pack's mints are handed
  to ticket 48 (that lane touches content.py); log/milestone id4 mints left
  unchecked (capped list / misroutes-one-delete — negligible, noted).
- Banner: width follows the longest row (pinned), boot-time note added,
  alternates line added. **Ride-along named per merge discipline:** ticket
  47's implementation (detect_lan_candidates ranking, lan_ip injection into
  create_app, candidates-computed-once in run.py) rode in this lane because
  it shares the boot path; 47's own tests land in its lane.
- Two review rounds; round 1 caught the WS dump half and the missing
  integration test. Gates: `python -m pytest` — 113 passed ×2.
