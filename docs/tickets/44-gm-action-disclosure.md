# 44 — GM action disclosure: silent heart loss, unlogged recall, duplicate names, silent truncation

**Status:** proposed
**Priority:** P3
**Area:** `server/actions.py` (pc/npc hearts_max, loot_assign, pc_add/
npc_add, long-form field caps), `client/src/views/GMView.tsx` (dropdowns)
**Found by:** 2026-10-06 full adversarial review

## Problem

Four places where the server changes or accepts something meaningful
without telling anyone:

1. **Reducing `hearts_max` below current hearts silently destroys
   hearts.** `pc["hearts"] = min(pc["hearts"], hm)`
   (`actions.py:198`, npc `:234`) — no log entry, no disclosure. Drop
   a PC 12→5 while they sit at 12, restore to 12: hearts are
   permanently 5 and nothing in the table log explains it.
2. **Loot recall is unlogged.** The assign branch logs (`actions.py:302`);
   the `pc_id: null` unassign branch (`:293-296`) does not — an item
   vanishing from a player's pack (or unclaimed by `pc_delete`) is
   invisible in the table log and the session report.
3. **Duplicate PC/NPC names are allowed** (`actions.py:176-185`,
   `:212-223`): two "Gandalf"s make the knock "seat as…" dropdown and
   loot-assign dropdowns ambiguous — the GM can seat/bind the wrong
   one. Ids disambiguate server-side, not the human.
4. **Silent truncation at every `sanitize_name` cap**
   (`actions.py:79, 92, 177, 213, 258, 269, 324, 335`): a 250-char
   loot description or 150-char milestone reason is clipped mid-word
   with no rejection or warning. Fine for names; dishonest for
   long-form fields the GM composed deliberately.

## Proposal

- Log the clamp (audience `"gm"` at minimum) when hearts exceed the
  new max; log recall like assign.
- Duplicate names: ruled — see Ruling below (UI discriminator; the
  server keeps allowing).
- Long-form fields (loot description, milestone reason, log text):
  reject over-cap with an ActionError instead of clipping; names/
  labels may stay clipped.

## Ruling (do not revisit)

Duplicate PC/NPC names (2026-10-06): **allow server-side, disambiguate
in the UI** — the defect is ambiguity in a dropdown, not the existence
of duplicates, and duplicates are normal for NPCs ("Bandit" ×3).
Server-side rejection is ruled out. The discriminator's fine default
is a numeral after the name ("Gandalf 2") in the two ambiguous
dropdowns (knock "seat as…", loot-assign). Future work, its own ticket
when wanted: let the GM assign a unique custom display name to a
character (which supersedes the numeral for that character).

## Acceptance criteria

- [ ] `tests/test_actions.py::test_hearts_max_shrink_is_logged` —
      pc at 12/12, `pc_update {hearts_max: 5}` → hearts 5 AND a log
      entry exists naming the pc (pin audience).
- [ ] `tests/test_actions.py::test_loot_recall_is_logged` — assign an
      item, `loot_assign {pc_id: null}` → `claimed_by` None AND a log
      entry exists; same after `pc_delete` unclaims.
- [ ] `tests/test_actions.py::test_duplicate_pc_name_allowed` — a
      second `pc_add {"Gandalf"}` succeeds with a distinct `pc_id`
      (pins the ruling's server half: no rejection).
- [ ] `tests/test_actions.py::test_overlong_longform_rejected` —
      `loot_add`/`loot_update` with a 250-char description raises
      ActionError (name over 40 chars may still clip — assert which).
- [ ] Client half (manual): two
      same-named PCs → the knock "seat as…" and loot-assign dropdowns
      show the numeral discriminator ("Gandalf 2"), visibly
      distinguishing them; `npm run build` green.
