# 46 — boot & commit robustness odds

**Status:** proposed
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
- [ ] Banner: `python run.py --help`-level manual check that the box
      renders with a long URL (or the width test is folded into a
      pure `banner_lines()` helper test if extracted).
