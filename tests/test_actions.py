import json

import pytest

from server import actions, state as st
from server.actions import ActionError


def act(s, action, args=None, role="gm", actor="GM", pc_id=None):
    actions.apply_action(s, role, actor, action, args or {}, pc_id=pc_id)


# -- hearts -----------------------------------------------------------------


def test_pc_hearts_clamp_to_bounds(seated_state):
    pc = seated_state["party"][0]
    act(seated_state, "pc_hearts", {"pc_id": pc["pc_id"], "delta": -10})
    assert pc["hearts"] == 0
    act(seated_state, "pc_hearts", {"pc_id": pc["pc_id"], "delta": +10})
    assert pc["hearts"] == pc["hearts_max"]


def test_player_can_shift_own_hearts_only(seated_state):
    # the negative here is rejected by apply_action's role routing (a player
    # calling a GM verb lands in _player_action's "unknown player action"
    # else-branch); ownership walls for real player verbs are pinned by the
    # claim/return tests and test_player_return_other_pc_item_rejected below
    pc = seated_state["party"][0]
    act(seated_state, "pc_add", {"name": "Brann"})
    brann = seated_state["party"][1]
    act(seated_state, "player_hearts", {"delta": -1}, role="player", actor="Sam", pc_id=pc["pc_id"])
    assert pc["hearts"] == pc["hearts_max"] - 1
    with pytest.raises(ActionError):
        act(seated_state, "pc_hearts", {"pc_id": brann["pc_id"], "delta": -1}, role="player", pc_id=pc["pc_id"])


def test_player_return_other_pc_item_rejected(seated_state):
    # the ownership wall through a real player verb: Brann's claim must not
    # be returnable by Sam (the gate-table rejections in the test above pass
    # via "unknown player action" and pin a different wall)
    item = seated_state["loot"][0]
    sam = seated_state["party"][0]
    act(seated_state, "pc_add", {"name": "Brann"})
    brann = seated_state["party"][1]
    act(seated_state, "player_claim", {"item_id": item["item_id"]}, role="player", actor="Brann", pc_id=brann["pc_id"])
    with pytest.raises(ActionError, match="not in your pack"):
        act(seated_state, "player_return", {"item_id": item["item_id"]}, role="player", pc_id=sam["pc_id"])
    assert item["claimed_by"] == brann["pc_id"]  # the claim survives the rejected return


def test_npc_partial_hearts(seated_state):
    npc = seated_state["npcs"][0]
    act(seated_state, "npc_hearts", {"npc_id": npc["npc_id"], "delta": -0.5})
    assert npc["hearts"] == 0.5


# -- loot -------------------------------------------------------------------


def test_claim_race_first_player_wins(seated_state):
    act(seated_state, "pc_add", {"name": "Brann"})
    item, brann = seated_state["loot"][0], seated_state["party"][1]
    pc = seated_state["party"][0]
    act(seated_state, "player_claim", {"item_id": item["item_id"]}, role="player", actor="Sam", pc_id=pc["pc_id"])
    assert item["claimed_by"] == pc["pc_id"]
    with pytest.raises(ActionError, match="already claimed"):
        act(seated_state, "player_claim", {"item_id": item["item_id"]}, role="player", pc_id=brann["pc_id"])


def test_player_return_only_own_items(seated_state):
    item = seated_state["loot"][0]
    pc = seated_state["party"][0]
    with pytest.raises(ActionError, match="not in your pack"):
        act(seated_state, "player_return", {"item_id": item["item_id"]}, role="player", pc_id=pc["pc_id"])
    act(seated_state, "player_claim", {"item_id": item["item_id"]}, role="player", pc_id=pc["pc_id"])
    act(seated_state, "player_return", {"item_id": item["item_id"]}, role="player", pc_id=pc["pc_id"])
    assert item["claimed_by"] is None


def test_gm_assign_and_recall(seated_state):
    item, pc = seated_state["loot"][0], seated_state["party"][0]
    act(seated_state, "loot_assign", {"item_id": item["item_id"], "pc_id": pc["pc_id"]})
    assert item["claimed_by"] == pc["pc_id"]
    act(seated_state, "loot_assign", {"item_id": item["item_id"], "pc_id": None})
    assert item["claimed_by"] is None
    with pytest.raises(ActionError):
        act(seated_state, "loot_assign", {"item_id": item["item_id"], "pc_id": None})


def test_pc_delete_returns_loot_and_unbinds(seated_state):
    pc = seated_state["party"][0]
    item = seated_state["loot"][0]
    act(seated_state, "loot_assign", {"item_id": item["item_id"], "pc_id": pc["pc_id"]})
    act(seated_state, "pc_delete", {"pc_id": pc["pc_id"]})
    assert seated_state["party"] == []
    assert seated_state["bindings"] == {}
    assert item["claimed_by"] is None


# -- role walls ---------------------------------------------------------------


def test_player_cannot_call_gm_actions(seated_state):
    pc = seated_state["party"][0]
    for action, args in [
        ("pc_add", {"name": "Sneaky"}),
        ("loot_add", {"name": "Sneaky"}),
        ("set_targets", {"default": 2, "scene": 2}),
        ("approve_join", {"device_token": "dev-1", "pc_id": pc["pc_id"]}),
        ("alarm_dismiss", {}),
    ]:
        with pytest.raises(ActionError):
            act(seated_state, action, args, role="player", pc_id=pc["pc_id"])


def test_unseated_player_cannot_act(seated_state):
    with pytest.raises(ActionError, match="not seated"):
        act(seated_state, "player_claim", {"item_id": "x"}, role="player", pc_id=None)


def test_unknown_action_rejected(seated_state):
    with pytest.raises(ActionError, match="unknown"):
        act(seated_state, "sudo_make_me_a_sandwich")


# -- timers -------------------------------------------------------------------


def test_alarm_timer_requires_duration(fresh_state):
    with pytest.raises(ActionError):
        act(fresh_state, "timer_add", {"label": "bad", "kind": "alarm"})
    with pytest.raises(ActionError):
        act(fresh_state, "timer_add", {"label": "bad", "kind": "rounds", "duration_s": 60})


def test_rounds_timer_ticks_down_to_alarm(fresh_state):
    act(fresh_state, "timer_add", {"label": "Patrol", "kind": "rounds", "rounds": 3})
    t = fresh_state["timers"][0]
    for _ in range(3):
        act(fresh_state, "timer_tick", {"timer_id": t["timer_id"]})
    assert t["status"] == "done" and t["rounds_left"] == 0
    assert [a["timer_id"] for a in fresh_state["alarm"]] == [t["timer_id"]]
    with pytest.raises(ActionError, match="at zero"):
        act(fresh_state, "timer_tick", {"timer_id": t["timer_id"]})
    act(fresh_state, "alarm_dismiss")
    assert fresh_state["alarm"] is None
    act(fresh_state, "timer_reset", {"timer_id": t["timer_id"]})
    assert t["rounds_left"] == 3 and t["status"] == "idle"


def test_alarm_expiry_is_server_computed(fresh_state, monkeypatch):
    fake = {"t": 1000.0}
    monkeypatch.setattr(st, "now", lambda: fake["t"])
    act(fresh_state, "timer_add", {"label": "Sundown", "kind": "alarm", "duration_s": 30})
    t = fresh_state["timers"][0]
    act(fresh_state, "timer_start", {"timer_id": t["timer_id"]})
    assert t["status"] == "running"
    fake["t"] += 29
    assert not st.check_timers(fresh_state, st.now())
    assert t["status"] == "running"
    fake["t"] += 2
    assert st.check_timers(fresh_state, st.now())
    assert t["status"] == "done"
    assert [a["timer_id"] for a in fresh_state["alarm"]] == [t["timer_id"]]


def test_paused_alarm_resumes_with_elapsed_credit(fresh_state, monkeypatch):
    fake = {"t": 1000.0}
    monkeypatch.setattr(st, "now", lambda: fake["t"])
    act(fresh_state, "timer_add", {"label": "Sundown", "kind": "alarm", "duration_s": 60})
    t = fresh_state["timers"][0]
    act(fresh_state, "timer_start", {"timer_id": t["timer_id"]})
    fake["t"] += 20
    act(fresh_state, "timer_pause", {"timer_id": t["timer_id"]})
    assert t["status"] == "paused"
    fake["t"] += 500  # paused time must not burn the clock
    act(fresh_state, "timer_start", {"timer_id": t["timer_id"]})  # resumed at t=1520 with 20s credit
    assert not st.check_timers(fresh_state, 1520 + 39)  # 59s elapsed
    assert st.check_timers(fresh_state, 1520 + 40)  # 60s elapsed: rings


# -- joins --------------------------------------------------------------------


def test_approve_join_binds_and_consumes_request(seated_state):
    seated_state["join_requests"].append({"device_token": "dev-2", "name": "Ash"})
    act(seated_state, "pc_add", {"name": "Brann"})
    brann = seated_state["party"][1]
    act(seated_state, "approve_join", {"device_token": "dev-2", "pc_id": brann["pc_id"]})
    assert seated_state["join_requests"] == []
    assert seated_state["bindings"]["dev-2"]["pc_id"] == brann["pc_id"]


def test_cannot_seat_two_devices_on_one_pc(seated_state):
    act(seated_state, "pc_add", {"name": "Brann"})
    brann = seated_state["party"][1]
    seated_state["join_requests"].append({"device_token": "dev-2", "name": "Ash"})
    with pytest.raises(ActionError, match="already seated"):
        act(seated_state, "approve_join", {"device_token": "dev-2", "pc_id": seated_state["party"][0]["pc_id"]})
    act(seated_state, "approve_join", {"device_token": "dev-2", "pc_id": brann["pc_id"]})


def test_reject_join(seated_state):
    seated_state["join_requests"].append({"device_token": "dev-2", "name": "Rando"})
    act(seated_state, "reject_join", {"device_token": "dev-2"})
    assert seated_state["join_requests"] == []


# -- misc ---------------------------------------------------------------------


def test_milestone_flow(seated_state):
    pc = seated_state["party"][0]
    act(seated_state, "milestone_add", {"pc_id": pc["pc_id"], "reason": "Held the causeway"})
    assert seated_state["milestones"][0]["pc_id"] == pc["pc_id"]
    mid = seated_state["milestones"][0]["id"]
    act(seated_state, "milestone_delete", {"id": mid})
    assert seated_state["milestones"] == []
    with pytest.raises(ActionError):
        act(seated_state, "milestone_delete", {"id": mid})


def test_targets_bounds(fresh_state):
    with pytest.raises(ActionError):
        act(fresh_state, "set_targets", {"default": 0, "scene": 14})
    act(fresh_state, "set_targets", {"default": 12, "scene": 16})
    assert fresh_state["targets"] == {"default": 12, "scene": 16}


def test_npc_reveal_logs_publicly(seated_state):
    npc = seated_state["npcs"][0]
    assert npc["visible"] is False
    act(seated_state, "npc_reveal", {"npc_id": npc["npc_id"]})
    assert npc["visible"] is True
    assert any("takes the stage" in e["text"] for e in seated_state["log"])


def test_session_reset_keeps_room_identity(fresh_state):
    s = fresh_state
    act(s, "pc_add", {"name": "Vex"})
    act(s, "session_reset")
    assert s["party"] == []
    assert s["room_code"] == "TEST"
    assert s["gm_token"] == "gm-secret"
    assert s["version"] == 1


def test_starter_load_idempotent(fresh_state):
    act(fresh_state, "starter_load", {"pack": "alfheim"})
    n_items = len(fresh_state["loot"])
    n_timers = len(fresh_state["timers"])
    assert n_items >= 4
    act(fresh_state, "starter_load", {"pack": "alfheim"})
    assert len(fresh_state["loot"]) == n_items
    assert len(fresh_state["timers"]) == n_timers


def test_starter_pack_rejects_traversal(fresh_state):
    with pytest.raises(ActionError):
        act(fresh_state, "starter_load", {"pack": "../secrets"})


def test_log_is_capped(fresh_state):
    for i in range(st.LOG_CAP + 50):
        st.add_log(fresh_state, "t", f"e{i}")
    assert len(fresh_state["log"]) == st.LOG_CAP


# -- arg intake honesty (ticket 36) ------------------------------------------


def test_update_null_fields_rejected(seated_state):
    pc = seated_state["party"][0]
    with pytest.raises(ActionError, match="cannot be null"):
        act(seated_state, "pc_update", {"pc_id": pc["pc_id"], "name": None})
    assert pc["name"] == "Vex"
    with pytest.raises(ActionError, match="cannot be null"):
        act(seated_state, "pc_update", {"pc_id": pc["pc_id"], "hearts_max": None})
    assert pc["hearts_max"] == 3
    npc = seated_state["npcs"][0]
    with pytest.raises(ActionError, match="cannot be null"):
        act(seated_state, "npc_update", {"npc_id": npc["npc_id"], "name": None})
    assert npc["name"] == "Sergeant Orla"
    item = seated_state["loot"][0]
    with pytest.raises(ActionError, match="cannot be null"):
        act(seated_state, "loot_update", {"item_id": item["item_id"], "bonus": None})
    assert item["bonus"] == ""
    act(seated_state, "timer_add", {"kind": "alarm", "label": "t", "duration_s": 60})
    timer = seated_state["timers"][0]
    with pytest.raises(ActionError, match="cannot be null"):
        act(seated_state, "timer_update", {"timer_id": timer["timer_id"], "label": None})
    assert timer["label"] == "t"


def test_abilities_must_be_list_of_strings(seated_state):
    with pytest.raises(ActionError, match="list of strings"):
        act(seated_state, "npc_add", {"name": "Orc", "abilities": "sword"})
    assert all(n["name"] != "Orc" for n in seated_state["npcs"])
    with pytest.raises(ActionError, match="list of strings"):
        act(seated_state, "npc_add", {"name": "Orc", "abilities": ["sword", 5]})
    npc = seated_state["npcs"][0]
    with pytest.raises(ActionError, match="list of strings"):
        act(seated_state, "npc_update", {"npc_id": npc["npc_id"], "abilities": "sword"})
    assert npc["abilities"] == []
    # null must never silently clear the list — same policy as every field
    with pytest.raises(ActionError, match="cannot be null"):
        act(seated_state, "npc_update", {"npc_id": npc["npc_id"], "abilities": None})
    assert npc["abilities"] == []


def test_bool_rejected_as_int(seated_state):
    with pytest.raises(ActionError, match="must be an integer"):
        act(seated_state, "pc_add", {"name": "Bool", "hearts_max": True})
    assert all(p["name"] != "Bool" for p in seated_state["party"])
    act(seated_state, "pc_add", {"name": "Real"})  # absent → default still applies
    assert seated_state["party"][1]["hearts_max"] == 3
    with pytest.raises(ActionError, match="must be an integer"):
        act(seated_state, "timer_add", {"kind": "alarm", "label": "t", "duration_s": True})
    with pytest.raises(ActionError, match="must be an integer"):
        act(seated_state, "timer_add", {"kind": "rounds", "label": "t", "rounds": False})
    with pytest.raises(ActionError, match="must be a number"):
        act(seated_state, "npc_add", {"name": "BoolNpc", "hearts_max": True})
    pc = seated_state["party"][0]
    with pytest.raises(ActionError, match="must be an integer"):
        act(seated_state, "pc_update", {"pc_id": pc["pc_id"], "hearts_max": True})
    assert pc["hearts_max"] == 3


def test_flag_strings_do_not_flip_disclosure(seated_state):
    npc = seated_state["npcs"][0]
    with pytest.raises(ActionError, match="must be true or false"):
        act(seated_state, "npc_reveal", {"npc_id": npc["npc_id"], "visible": "false"})
    assert npc["visible"] is False
    act(seated_state, "npc_reveal", {"npc_id": npc["npc_id"], "visible": True})
    assert npc["visible"] is True
    act(seated_state, "npc_reveal", {"npc_id": npc["npc_id"]})  # absent → default
    assert npc["visible"] is True
    # the chosen policy is strict: a truthy string is rejected outright, so
    # no log entry exists that could ever have leaked to the players
    log_len = len(seated_state["log"])
    with pytest.raises(ActionError, match="must be true or false"):
        act(seated_state, "log_note", {"text": "private", "share": "false"})
    assert len(seated_state["log"]) == log_len
    act(seated_state, "log_note", {"text": "public", "share": True})
    assert seated_state["log"][-1]["audience"] == "all"
    act(seated_state, "log_note", {"text": "default"})
    assert seated_state["log"][-1]["audience"] == "gm"


def test_non_string_names_rejected(seated_state):
    with pytest.raises(ActionError, match="must be a string"):
        act(seated_state, "pc_add", {"name": {"x": 1}})
    with pytest.raises(ActionError, match="must be a string"):
        act(seated_state, "pc_add", {"name": ["a"]})
    with pytest.raises(ActionError, match="must be a string"):
        act(seated_state, "log_note", {"text": 5})
    with pytest.raises(ActionError, match="must be a string"):
        act(seated_state, "set_title", {"title": 12})
    assert seated_state["title"] == "Untitled session"


# -- hub robustness: validate-then-mutate, coercion, pack validation (ticket 32)


def test_rejected_update_leaves_state_untouched(seated_state):
    pc = seated_state["party"][0]
    with pytest.raises(ActionError, match="hearts_max must be 1..20"):
        act(seated_state, "pc_update", {"pc_id": pc["pc_id"], "name": "Newname", "hearts_max": 99})
    assert pc["name"] == "Vex" and pc["hearts_max"] == 3

    npc = seated_state["npcs"][0]
    with pytest.raises(ActionError, match="bad effort_die"):
        act(seated_state, "npc_update", {"npc_id": npc["npc_id"], "name": "Renamed", "effort_die": "d20"})
    assert npc["name"] == "Sergeant Orla"

    item = seated_state["loot"][0]
    with pytest.raises(ActionError, match="bad tier"):
        act(seated_state, "loot_update", {"item_id": item["item_id"], "name": "Renamed", "tier": "legendary"})
    assert item["name"] == "Ford signet ring"

    act(seated_state, "timer_add", {"kind": "alarm", "label": "t", "duration_s": 60})
    t = seated_state["timers"][0]
    with pytest.raises(ActionError, match="duration_s must be 1..86400"):
        act(seated_state, "timer_update", {"timer_id": t["timer_id"], "label": "Renamed", "duration_s": 0})
    assert t["label"] == "t" and t["duration_s"] == 60


def test_non_coercible_numbers_rejected(seated_state):
    pc = seated_state["party"][0]
    with pytest.raises(ActionError, match="must be a number"):
        act(seated_state, "pc_hearts", {"pc_id": pc["pc_id"], "delta": "abc"})
    with pytest.raises(ActionError, match="must be a number"):
        act(seated_state, "pc_hearts", {"pc_id": pc["pc_id"], "delta": True})
    with pytest.raises(ActionError, match="finite"):
        act(seated_state, "pc_hearts", {"pc_id": pc["pc_id"], "delta": float("nan")})
    assert pc["hearts"] == pc["hearts_max"]  # untouched by every rejection
    with pytest.raises(ActionError, match="must be an integer"):
        act(seated_state, "set_targets", {"default": "12a", "scene": 3})
    with pytest.raises(ActionError, match="missing 'id'"):
        act(seated_state, "milestone_delete", {"id": ""})


def test_malformed_pack_fails_without_partial_apply(seated_state, monkeypatch, tmp_path):
    from server import content

    monkeypatch.setattr(content, "PACKS_DIR", str(tmp_path))
    n_loot, n_timers = len(seated_state["loot"]), len(seated_state["timers"])

    (tmp_path / "bad.json").write_text(
        json.dumps({"loot": [{"name": "Good ring", "tier": "common"}],
                    "timers": [{"label": "Bad timer", "kind": "alarm"}]}),  # missing duration_s
        encoding="utf-8")
    with pytest.raises(ActionError, match="duration_s"):
        act(seated_state, "starter_load", {"pack": "bad"})
    assert len(seated_state["loot"]) == n_loot and len(seated_state["timers"]) == n_timers

    (tmp_path / "nokey.json").write_text(json.dumps({"loot": [{"tier": "common"}]}), encoding="utf-8")
    with pytest.raises(ActionError, match="needs a name"):
        act(seated_state, "starter_load", {"pack": "nokey"})

    (tmp_path / "tier.json").write_text(json.dumps({"loot": [{"name": "X", "tier": "legendary"}]}), encoding="utf-8")
    with pytest.raises(ActionError, match="tier"):
        act(seated_state, "starter_load", {"pack": "tier"})

    (tmp_path / "list.json").write_text(json.dumps([1]), encoding="utf-8")
    with pytest.raises(ActionError, match="JSON object"):
        act(seated_state, "starter_load", {"pack": "list"})

    (tmp_path / "str.json").write_text(json.dumps({"loot": [{"name": "X", "bonus": 5}]}), encoding="utf-8")
    with pytest.raises(ActionError, match="must be strings"):
        act(seated_state, "starter_load", {"pack": "str"})


# -- timer state machine consistency (ticket 42) ------------------------------


def _run_rounds_to_done(s, label):
    act(s, "timer_add", {"kind": "rounds", "label": label, "rounds": 1})
    t = next(x for x in s["timers"] if x["label"] == label)
    act(s, "timer_tick", {"timer_id": t["timer_id"]})
    return t


def test_timer_update_clears_ringing_alarm(fresh_state):
    t = _run_rounds_to_done(fresh_state, "ambush")
    assert fresh_state["alarm"]  # ringing
    act(fresh_state, "timer_update", {"timer_id": t["timer_id"], "rounds": 5})
    assert fresh_state["alarm"] is None  # re-rounding = give it more rounds
    assert t["status"] == "idle" and t["rounds_left"] == 5

    # timer_start on a done alarm timer clears its ring too
    act(fresh_state, "timer_add", {"kind": "alarm", "label": "boom", "duration_s": 1})
    a = next(x for x in fresh_state["timers"] if x["label"] == "boom")
    act(fresh_state, "timer_start", {"timer_id": a["timer_id"]})
    a["status"] = "done"  # let it ring out (watcher would do this)
    fresh_state["alarm"] = [{"timer_id": a["timer_id"], "label": "boom"}]
    act(fresh_state, "timer_start", {"timer_id": a["timer_id"]})  # start again
    assert fresh_state["alarm"] is None  # the stale ring went with it


def test_timer_update_blank_label_keeps_label(fresh_state):
    act(fresh_state, "timer_add", {"kind": "alarm", "label": "Sundown", "duration_s": 30})
    t = fresh_state["timers"][0]
    act(fresh_state, "timer_update", {"timer_id": t["timer_id"], "label": "   "})
    assert t["label"] == "Sundown"
    act(fresh_state, "timer_update", {"timer_id": t["timer_id"], "label": "Dusk"})
    assert t["label"] == "Dusk"


def test_timer_update_wrong_kind_field_rejected(fresh_state):
    act(fresh_state, "timer_add", {"kind": "alarm", "label": "t", "duration_s": 60})
    a = fresh_state["timers"][0]
    with pytest.raises(ActionError, match="rounds belongs to a rounds timer"):
        act(fresh_state, "timer_update", {"timer_id": a["timer_id"], "rounds": 5})
    assert a["duration_s"] == 60  # untouched by the rejection
    act(fresh_state, "timer_add", {"kind": "rounds", "label": "r", "rounds": 3})
    r = fresh_state["timers"][1]
    with pytest.raises(ActionError, match="duration_s belongs to an alarm timer"):
        act(fresh_state, "timer_update", {"timer_id": r["timer_id"], "duration_s": 60})
    assert r["rounds_total"] == 3
    # coercion strictness matches timer_add (ticket 36's _opt_int)
    with pytest.raises(ActionError, match="must be an integer"):
        act(fresh_state, "timer_update", {"timer_id": a["timer_id"], "duration_s": "12"})
    with pytest.raises(ActionError, match="must be an integer"):
        act(fresh_state, "timer_update", {"timer_id": a["timer_id"], "duration_s": 10.5})
    # re-timing a rung-out alarm clears its stale ring, like the rounds branch
    a["status"] = "done"
    fresh_state["alarm"] = [{"timer_id": a["timer_id"], "label": "t"}]
    act(fresh_state, "timer_update", {"timer_id": a["timer_id"], "duration_s": 90})
    assert fresh_state["alarm"] is None
    assert a["duration_s"] == 90


def test_pause_and_tick_unknown_timer_say_no_such_timer(fresh_state):
    with pytest.raises(ActionError, match="no such timer"):
        act(fresh_state, "timer_pause", {"timer_id": "tm_nope"})
    with pytest.raises(ActionError, match="no such timer"):
        act(fresh_state, "timer_tick", {"timer_id": "tm_nope"})


def test_two_alarms_same_tick_both_surface(fresh_state, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(st, "now", lambda: clock["now"])
    for label in ("first", "second"):
        act(fresh_state, "timer_add", {"kind": "alarm", "label": label, "duration_s": 10})
        t = next(x for x in fresh_state["timers"] if x["label"] == label)
        act(fresh_state, "timer_start", {"timer_id": t["timer_id"]})
    clock["now"] = 1011.0  # both expire in the same tick
    assert st.check_timers(fresh_state, st.now())
    labels = {a["label"] for a in fresh_state["alarm"]}
    assert labels == {"first", "second"}  # one did NOT swallow the other
    act(fresh_state, "alarm_dismiss")
    assert fresh_state["alarm"] is None


def test_snapshot_old_single_alarm_dict_becomes_queue(tmp_path):
    raw = {"schema": st.SCHEMA, "room_code": "ROOM", "gm_token": "tok",
           "alarm": {"timer_id": "tm_1", "label": "old"}}
    (tmp_path / st._SNAPSHOT_NAME).write_text(json.dumps(raw), encoding="utf-8")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state["alarm"] == [{"timer_id": "tm_1", "label": "old"}]
    assert reason is None


def test_claim_announcement_is_player_audience(seated_state):
    # pins the server half of the player-facing table log (ticket 39): the
    # claim announcement the client renders must be audience "all"
    item = seated_state["loot"][0]
    pc = seated_state["party"][0]
    act(seated_state, "player_claim", {"item_id": item["item_id"]}, role="player", actor="Sam", pc_id=pc["pc_id"])
    entry = seated_state["log"][-1]
    assert entry["audience"] == "all"
    assert "claimed" in entry["text"] and pc["name"] in entry["text"]


# -- GM console input robustness, server half (ticket 50) ---------------------


def test_set_title_empty_allowed(seated_state):
    # the GM clears the title field — an empty title is legitimate
    act(seated_state, "set_title", {"title": ""})
    assert seated_state["title"] == ""
    act(seated_state, "set_title", {"title": "   "})
    assert seated_state["title"] == ""
    act(seated_state, "set_title", {"title": "The Siege of Ford"})
    assert seated_state["title"] == "The Siege of Ford"


def test_milestone_delete_by_id(fresh_state):
    act(fresh_state, "pc_add", {"name": "Vex"})
    pc = fresh_state["party"][0]
    act(fresh_state, "milestone_add", {"pc_id": pc["pc_id"], "reason": "first"})
    act(fresh_state, "milestone_add", {"pc_id": pc["pc_id"], "reason": "second"})
    ids = [m["id"] for m in fresh_state["milestones"]]
    assert ids[0] != ids[1]
    act(fresh_state, "milestone_delete", {"id": ids[0]})
    assert [m["reason"] for m in fresh_state["milestones"]] == ["second"]  # the right one
    with pytest.raises(ActionError, match="no such milestone"):
        act(fresh_state, "milestone_delete", {"id": ids[0]})


def test_set_targets_delta_shape(fresh_state):
    # the TN card sends {which, delta} so fast taps can't lose decrements
    act(fresh_state, "set_targets", {"which": "default", "delta": -1})
    assert fresh_state["targets"]["default"] == 11
    act(fresh_state, "set_targets", {"which": "scene", "delta": +1})
    assert fresh_state["targets"]["scene"] == 15
    act(fresh_state, "set_targets", {"which": "default", "delta": -20})  # clamped
    assert fresh_state["targets"]["default"] == 2
    with pytest.raises(ActionError, match="which"):
        act(fresh_state, "set_targets", {"which": "middle", "delta": 1})
    # absolute shape still works
    act(fresh_state, "set_targets", {"default": 12, "scene": 14})
    assert fresh_state["targets"] == {"default": 12, "scene": 14}
