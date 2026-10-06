# 36 — action arg intake: the silent corruption class

**Status:** proposed
**Priority:** P2
**Area:** `server/actions.py` (update handlers, `npc_add`/`npc_update`
abilities, boolean flags), extends ticket 32's central-coercion proposal
**Found by:** 2026-10-06 full adversarial review

## Problem

Ticket 32 item 2 covers wrong-typed args that *crash* the handler.
These sibling cases don't crash — they corrupt state silently:

1. **JSON `null` becomes the string `"None"`.** Every update handler
   stringifies without a null check: `str(args["name"])` at
   `actions.py:190` (also `:108, 192, 228, 276, 282, 284`). `str(None)`
   is `"None"`, which is truthy, so even the `or pc["name"]` fallback
   never fires. `pc_update {pc_id, name: null}` renames the character
   to literally "None"; same for timer labels, loot bonus/description,
   npc names. Committed, broadcast, snapshotted.
2. **A string `abilities` explodes per character.** No
   `isinstance(..., list)` check (`actions.py:222, 240`):
   `npc_add {abilities: "sword,shield"}` iterates the string and
   commits abilities `s · w · o · r · d · , …` on every client.
   A dict yields its keys.
3. **Booleans pass the int gates.** `isinstance(True, int)` is `True`:
   `pc_add {hearts_max: true}` commits a PC whose `hearts`/`hearts_max`
   are the JSON booleans `true` (`actions.py:181`) — the hearts UI
   breaks, and `pc_update {hearts_max: 5}` computes `min(True, 5) ==
   True` so it never heals. `timer_add {duration_s: true}` is a
   1-second alarm (`:96`), `rounds: true` a 1-round timer (`:100`).
4. **Truthy strings flip disclosure flags.**
   `bool(args.get("visible", False))` (`actions.py:223, 248`) and the
   `share` read (`:336`): `npc_reveal {visible: "false"}` reveals the
   NPC to players; `log_note {share: "false"}` publishes a private GM
   note to the table.
5. **`str()` of dict/list renders Python `repr` into table text.**
   `pc_add {name: {"x": 1}}` creates a character named `{'x': 1}`
   (all `str(args[...])` name/label/text sites).

The add-handlers' `_need` pattern proves the intent; the update path
just skips it. Implementing this ticket largely implements the
coercion half of ticket 32's proposal — coordinate, don't duplicate.

## Proposal

Central field helpers used by add *and* update handlers (per ticket
32's validate-before-mutate shape):

- `_str_field(args, key)` → `None`/absent means "field absent"; a
  present non-string raises `ActionError` (no `str()` coercion).
- `_int_field` rejects `bool` explicitly (`isinstance(x, int) and not
  isinstance(x, bool)`).
- Flags: `args.get("visible") is True` (or reject non-bool).
- `abilities`: require a list of strings.

## Acceptance criteria

- [ ] `tests/test_actions.py::test_update_null_fields_rejected` —
      parametrized over `pc_update {name: None}`, `timer_update
      {label: None}`, `npc_update {name: None}`, `loot_update
      {bonus: None}`: raises ActionError AND the field is unchanged in
      state. (Today: field becomes `"None"`.)
- [ ] `tests/test_actions.py::test_abilities_must_be_list` —
      `npc_add {abilities: "sword"}` → ActionError, no NPC appended;
      `npc_update` same.
- [ ] `tests/test_actions.py::test_bool_rejected_as_int` —
      parametrized: `pc_add {hearts_max: true}`, `timer_add
      {kind: "alarm", duration_s: true}`, `timer_add {kind: "rounds",
      rounds: true}` all raise ActionError.
- [ ] `tests/test_actions.py::test_flag_strings_do_not_flip_disclosure`
      — `npc_reveal {visible: "false"}` leaves the NPC hidden (or
      raises — pin whichever is chosen); `log_note {share: "false"}`
      produces an audience-`"gm"` entry.
- [ ] `tests/test_actions.py::test_non_string_names_rejected` —
      `pc_add {name: {"x": 1}}` and `{name: ["a"]}` raise ActionError
      (no `{'x': 1}` in `state["party"]`).
