# 35 — snapshot durability, restore validation, honest fallback

**Status:** completed — implemented and code-reviewed 2026-10-06 (three review rounds; rounds 1–2 surfaced two P1s and a P2 in the first implementation, all fixed).
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

## Implementation notes (2026-10-06)

Landed in `server/state.py`, `server/app.py`, `run.py`, 
`tests/test_persistence.py`:

- Durability: `save_snapshot` flush+fsyncs before `os.replace`, and keeps
  one fsynced previous generation (`state.json.bak`, manual read/write
  loop). `clear_snapshot` removes `.tmp`, then `.bak`, then main — a crash
  mid-clear can never resurrect a "deleted" session.
- Restore: `load_snapshot` now returns `(state, reason)` and normalizes
  through `_normalize_state`: backfills missing keys from the `new_state()`
  template, mints identity when gone, strips fossil keys top-level and
  per-entry (`_ENTRY_SHAPE` allowed/required sets), and DROPS entries
  missing required keys with a disclosed note. `app.load_reason` carries
  the fallback reason; `run.py` prints it as a banner NOTE line (banner
  extracted to `banner_lines()` for testability — byte-identical output).
- Fallback matrix: clean load → (state, None); absent main+bak →
  (None, None) silent fresh start; damaged OR missing main with a valid
  bak → bak restored with disclosure; both gone/damaged → (None, reason).
  Reads use `utf-8-sig`; `UnicodeDecodeError` is caught (byte-garbage
  snapshots disclose, never crash boot).
- **AC deviation (documented):** the BOM acceptance criterion originally
  said a BOM'd snapshot falls back with a reason; the proposal's own
  `utf-8-sig` fix supersedes that — a BOM'd snapshot now LOADS cleanly
  (`test_bom_snapshot_loads` pins the better contract). Only a zero-byte
  file discloses-and-falls-back.
- **AC deviation (documented):** the banner criterion's "appears exactly
  once on stdout" is pinned via `banner_lines` composition
  (`test_banner_discloses_the_fallback_exactly_once`) rather than capturing
  `run.main` output.
- Review rounds: round 1 found the first implementation's normalization
  kept entries missing required keys (the exact KeyError class this ticket
  kills) and its milestone allowlist would have eaten live `pc_name` data
  on every restart — both fixed with required-key sets and a full-shape
  lossless round-trip test. Round 2 found `join_requests` still didn't
  require `name` (approve/reject index it) — fixed. Round 3 approved.
- Gates: `python -m pytest` — 56 passed.
