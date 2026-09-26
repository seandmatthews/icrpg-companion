import pytest

from server import state as st


@pytest.fixture()
def fresh_state():
    return st.new_state("TEST", "gm-secret")


@pytest.fixture()
def seated_state(fresh_state):
    """A state with one PC, one player binding, one pool item, one NPC."""
    from server import actions

    s = fresh_state
    actions.apply_action(s, "gm", "GM", "pc_add", {"name": "Vex", "player_label": "Sam", "hearts_max": 3})
    actions.apply_action(s, "gm", "GM", "loot_add", {"name": "Ford signet ring", "tier": "uncommon"})
    actions.apply_action(s, "gm", "GM", "npc_add", {"name": "Sergeant Orla", "hearts_max": 1})
    s["bindings"]["dev-1"] = {"pc_id": s["party"][0]["pc_id"], "player_name": "Sam"}
    return s
