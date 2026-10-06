# 35 — snapshot durability, restore validation, honest fallback

**Status:** proposed
**Priority:** P2
**Area:** `server/state.py` (save_snapshot, load_snapshot), `run.py` (banner)
**Found by:** 2026-10-06 full adversarial review

## Problem

Three related defects in the "a crash mid-session costs nothing"
promise (state.py module docstring):

1. **Power loss can erase the session.** `save_snapshot`
   (`state.py:243-249`) never `flush()`es or `fsync()`s before
   `os.replace`. On NTFS the rename is atomic but the file's data may
   never reach the platter: after a hard reset, `state.json` can be
   zero-length or garbage. Process crashes are safe (page cache); a
   table-side power cut is not. No previous generation is kept.
2. **Restore validates one string.** `load_snapshot`
   (`state.py:252-264`) checks only `state.get("schema") == SCHEMA`.
   A JSON-valid file with the right schema string but missing keys
   (`party`, `bindings`, `join_requests`, `targets`, … — e.g. from an
   older build) loads fine and then the first broadcast raises
   `KeyError` (`hub.py:47`, `state.py:192,200`); every client dies in
   a reconnect loop with no error frame. Conversely, keys removed from
   the code are never stripped: the current `data/state.json` carries
   fossil `minted` / `player_name` fields that no current code writes
   and that flow to every client forever.
3. **Fallback is silent.** Corrupt file, UTF-8 BOM (a user who peeked
   at `state.json` in Notepad adds one), `PermissionError`, and
   absent file all collapse into the same silent `None` → fresh boot
   with a *new room code and GM key*. If nobody remembers the old
   code, the session loss is indistinguishable from "it just reset".

## Proposal

- `f.flush(); os.fsync(f.fileno())` before `os.replace`; optionally
  keep one previous generation (`state.json.bak`) and try it on
  fallback.
- On load, normalize against the `new_state()` template: backfill
  missing keys with defaults, drop unknown keys. Bump the schema
  string version whenever the shape changes.
- Read with `encoding="utf-8-sig"`.
- Surface the fallback reason (return `(state, reason)` or log a
  warning) and print one banner line in `run.py`:
  "previous snapshot unreadable (<reason>) — started fresh".

## Acceptance criteria

- [ ] `tests/test_persistence.py::test_snapshot_missing_keys_backfilled`
      — write `{"schema": SCHEMA}` (and a variant missing only
      `join_requests`) to the snapshot path; `load_snapshot` returns a
      usable state containing `party`/`bindings`/`join_requests`/`log`
      (not None), and booting a server against it serves a working
      bootstrap. Today this boots then KeyErrors on first broadcast.
- [ ] `tests/test_persistence.py::test_snapshot_unknown_keys_stripped`
      — a snapshot containing a `{"minted": false}` loot field (the
      fossil shape) loads with that key absent from the loaded state
      and from a GM broadcast frame.
- [ ] `tests/test_persistence.py::test_snapshot_bom_and_empty_disclosed`
      — a BOM-prefixed snapshot and a zero-byte file both return
      `(None, reason)` with a distinct reason string, not a silent
      None; pin the reason text reaches the caller.
- [ ] `tests/test_persistence.py::test_fallback_reason_reaches_banner`
      — boot via the app factory with a corrupt snapshot and capture
      stdout/banner (or the reason plumbing chosen): the disclosure
      line appears exactly once.
- [ ] `tests/test_persistence.py::test_snapshot_unicode_round_trip` —
      PCs/loot with accented and CJK names survive save → load →
      GM-view equality (the existing round-trip test is ASCII-only).
- [ ] fsync/.bak are not directly assertable in pytest; pin them by
      code-review note in Implementation notes, and (if .bak lands)
      `tests/test_persistence.py::test_corrupt_main_falls_back_to_bak`
      — valid `.bak` + corrupt main → previous session restored.
