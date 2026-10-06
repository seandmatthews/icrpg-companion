# 45 — name unicode normalization: invisible knock twins and bidi/zero-width injection

**Status:** proposed
**Priority:** P3
**Area:** `server/state.py` (sanitize_name)
**Found by:** 2026-10-06 full adversarial review

## Problem

`sanitize_name` is `re.sub(r"\s+", " ", (s or "")).strip()[:cap]`
(`state.py:273-274`) — no Unicode normalization, no control/zero-width
stripping:

- NFC and NFD forms of "Café" are different strings that render
  identically: two knocks can look identical in the GM's approve
  panel, the GM approves the wrong one, and nothing explains why
  hearts ended up on the "other" twin.
- Category Cc control chars (most of U+0000–U+001F are not `\s`), Cf
  zero-width chars (U+200B/U+200D), and U+202E (RTL override, which
  visually reverses following text) all pass through into names,
  labels, and log text on every client.

The `[:cap]` slice is code-point-safe (verified) — the gap is purely
normalization/filtering.

## Proposal

In `sanitize_name`: `unicodedata.normalize("NFC", s)`, then drop
characters with `unicodedata.category(c) in {"Cc", "Cf"}` before the
whitespace collapse. (Store normalized; no migration needed —
existing names pass through on next edit, or a one-shot re-sanitize on
snapshot load if cheap.)

## Acceptance criteria

- [ ] `tests/test_actions.py::test_nfd_and_nfc_names_normalized` —
      knock/approve flow: `hello_player` with the NFD form of "Café"
      then a second device with the NFC form → the GM view shows
      either one normalized name (dedup path) or two *visibly*
      different names; the chosen behavior is pinned, and
      `sanitize_name("Cafe\u0301") == sanitize_name("Café")` holds in
      the normalized case.
- [ ] `tests/test_actions.py::test_control_and_zero_width_stripped` —
      a name containing U+200B and U+202E is stored without them
      (assert the stored string contains only printable categories);
      a log note and a loot name likewise.
- [ ] `tests/test_persistence.py::test_snapshot_unicode_round_trip` —
      accented/CJK names survive save → load → GM-view equality
      end-to-end (never exercised today; if ticket 35 lands first,
      its round-trip test covers this — cross-reference instead of
      duplicating).
