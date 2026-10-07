# 48 — content pack intake: fields bypass action-layer validation; BOM mislabeled corrupt

**Status:** completed — implemented and code-reviewed 2026-10-06 (two review rounds).
**Priority:** P3
**Area:** `server/content.py` (load_pack, _pack_path read), extends
ticket 32 item 4
**Found by:** 2026-10-06 full adversarial review

## Problem

Pack entries skip every validation the interactive actions enforce
(`content.py:46-49` vs `actions.py:257-271`):

- `tier` is passed through unchecked — a pack with
  `"tier": "legendary"` silently renders an unstyled tier chip on
  every client (no such tier exists in `TIERS`).
- `name` / `bonus` / `description` skip `sanitize_name` and the
  length caps the actions apply — a pack is the one input that comes
  from files rather than args, and it is the least validated.
- The pack file is read with `encoding="utf-8"` (`content.py:28`); a
  BOM (any Windows editor default) raises `JSONDecodeError`, which the
  handler reports as "starter pack 'alfheim' is corrupt" — a wrong
  message; the JSON is fine.

Out of scope here (already ticket 32 item 4): missing required keys
raising `KeyError` through `apply_action`, and entries appended before
a crash staying in state (partial apply).

## Proposal

- Route pack fields through the same validators the actions use
  (tier ∈ `TIERS`, `sanitize_name` + caps on strings) so a pack and
  the GM console produce identical shapes — after ticket 36/32's
  central helpers exist, reuse them.
- Open with `encoding="utf-8-sig"`.
- Decide: invalid entry → reject the whole pack (ActionError, nothing
  applied) rather than skipping the entry — matches ticket 32's
  all-or-nothing direction for packs.

## Acceptance criteria

- [ ] `tests/test_actions.py::test_pack_bom_loads` — a tmp pack
      written with a UTF-8 BOM (monkeypatched `PACKS_DIR`) loads
      successfully; the "corrupt" wording is reserved for actual
      JSON errors.
- [ ] `tests/test_actions.py::test_pack_bad_tier_rejected` — a pack
      entry with `"tier": "legendary"` → ActionError naming the entry,
      state unchanged (no half-applied loot).
- [ ] `tests/test_actions.py::test_pack_unsanitized_fields_normalized`
      — a pack name containing a zero-width char / over cap produces
      the same stored shape `loot_add` would produce (equality assert
      against the action-built item, minus ids/timestamps).
- [ ] The missing-key/partial-apply regressions land with ticket 32's
      acceptance tests — this ticket's tests must not duplicate them,
      only the tier/sanitize/BOM surface.

## Implementation notes (2026-10-06)

Landed in `server/content.py` + tests:

- utf-8-sig open (a BOM is not corruption; pinned).
- targets: range 2..30 and unknown-keys rejection, matching set_targets
  exactly; pinned including non-default applied values (round 2 caught the
  first test's positive case passing vacuously — `and`-chained clears plus
  default-value asserts).
- **Console-identical intake (the central AC):** pack loot names and timer
  labels go through sanitize_name (cap 60, empty-after rejected) and
  descriptions through `_long_form` (over-cap rejects the WHOLE pack, all-
  or-nothing) — a pack with a zero-width name or a 250-char description can
  no longer land shapes the GM console could never produce. The round-1 P1
  (raw name/label passthrough — invisible names entering state) is closed,
  and it also fixed the name-dedup: sanitized-vs-sanitized comparison.
- Id remint loops in load_pack (handed off from ticket 46), pinned by a
  300-item pool test.
- Gates: `python -m pytest` — 122 passed ×2; alfheim.json passes the stricter
  validation unchanged.
