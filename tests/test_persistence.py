import json
import os

from server import state as st


def test_snapshot_round_trip(tmp_path):
    s = st.new_state("ROOM", "tok")
    st.add_log(s, "GM", "hello")
    s["party"].append(st.new_pc("Vex", "Sam", 3))
    st.save_snapshot(s, str(tmp_path))

    loaded, reason = st.load_snapshot(str(tmp_path))
    assert reason is None
    assert loaded == s
    assert loaded["room_code"] == "ROOM"


def test_snapshot_unicode_round_trip(tmp_path):
    s = st.new_state("ROOM", "tok")
    s["party"].append(st.new_pc("Café Ñoño", "José", 3))
    s["party"].append(st.new_pc("中村", "Nakamura", 2))
    s["loot"].append(st.new_item("Épée ofStorms ☔", "rare", "+2 vs rain", "grüne Blätter"))
    st.save_snapshot(s, str(tmp_path))

    loaded, reason = st.load_snapshot(str(tmp_path))
    assert reason is None
    assert loaded["party"][0]["name"] == "Café Ñoño"
    assert loaded["party"][1]["name"] == "中村"
    assert loaded["loot"][0]["name"] == "Épée ofStorms ☔"


def test_snapshot_write_is_atomic(tmp_path):
    s = st.new_state("ROOM", "tok")
    st.save_snapshot(s, str(tmp_path))
    names = os.listdir(tmp_path)
    assert names == [st._SNAPSHOT_NAME]  # no .tmp litter on a first save


def test_snapshot_missing_keys_backfilled(tmp_path):
    # the torn-but-valid case: right schema string, nothing else — this used
    # to boot and then KeyError every broadcast (ticket 35)
    (tmp_path / st._SNAPSHOT_NAME).write_text(json.dumps({"schema": st.SCHEMA}), encoding="utf-8")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state is not None
    for key in ("targets", "timers", "party", "npcs", "loot", "join_requests", "rejections", "bindings", "log", "milestones", "alarm"):
        assert key in state, key
    assert state["party"] == [] and state["bindings"] == {} and state["alarm"] is None
    # identity is backfilled and the repair is disclosed, never silent
    assert isinstance(state["room_code"], str) and state["room_code"]
    assert isinstance(state["gm_token"], str) and state["gm_token"]
    assert reason and "minted" in reason

    # the AC's second variant: a real snapshot missing only one collection
    raw = {"schema": st.SCHEMA, "room_code": "ROOM", "gm_token": "tok", "party": [], "log": []}
    (tmp_path / st._SNAPSHOT_NAME).write_text(json.dumps(raw), encoding="utf-8")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state["join_requests"] == [] and state["bindings"] == {}
    assert reason is None


def test_snapshot_partial_boots_and_serves_bootstrap(tmp_path):
    # the pin that matters: a partial snapshot boots to a WORKING table, not
    # a server that KeyErrors on first contact
    (tmp_path / st._SNAPSHOT_NAME).write_text(json.dumps({"schema": st.SCHEMA}), encoding="utf-8")
    from test_ws_flow import TestServer

    with TestServer(str(tmp_path), fresh=False) as srv:
        import urllib.request

        http_base = srv.ws_base.replace("ws://", "http://")
        with urllib.request.urlopen(http_base + "/api/bootstrap", timeout=5) as r:
            body = json.loads(r.read())
        assert body["room_code"] == srv.app.state_model["room_code"]


def test_snapshot_invalid_entries_dropped_with_note(tmp_path):
    # entries missing required keys are dropped and DISCLOSED, never kept to
    # KeyError the views later, and never silently vanished
    raw = {
        "schema": st.SCHEMA,
        "room_code": "ROOM",
        "gm_token": "tok",
        "party": [{}],
        "log": [{}],
        "loot": [{"item_id": "it_1", "name": "Ring", "claimed_by": None, "minted": False}],
    }
    (tmp_path / st._SNAPSHOT_NAME).write_text(json.dumps(raw), encoding="utf-8")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state["party"] == [] and state["log"] == []
    assert state["loot"] == [{"item_id": "it_1", "name": "Ring", "claimed_by": None}]  # fossil stripped
    assert reason and "dropped" in reason and "minted" not in json.dumps(state)


def test_snapshot_full_shape_round_trip(tmp_path):
    # every collection, including the milestone pc_name field current code
    # writes — a round trip must be lossless (this pins the fossil-stripper
    # against eating live data)
    s = st.new_state("ROOM", "tok")
    pc = st.new_pc("Vex", "Sam", 3)
    s["party"].append(pc)
    npc = st.new_npc("Boss", 5, "d6", ["smash"], visible=False)
    s["npcs"].append(npc)
    s["loot"].append(st.new_item("Ring", "common", "+1", "glows"))
    t = st.new_timer("wandering", "alarm", 600, None)
    s["timers"].append(t)
    s["join_requests"].append({"device_token": "dev-1", "name": "Sam"})
    s["bindings"]["dev-1"] = {"pc_id": pc["pc_id"]}
    s["log"].append({"ts": st.now_iso(), "audience": "gm", "actor": "GM", "text": "secret"})
    s["milestones"].append({"pc_id": pc["pc_id"], "pc_name": "Vex", "reason": "cleared the vault", "ts": st.now_iso()})
    s["rejections"].append({"device_token": "dev-turned-away", "name": "Rando"})
    st.save_snapshot(s, str(tmp_path))
    loaded, reason = st.load_snapshot(str(tmp_path))
    assert reason is None
    assert loaded == s


def test_snapshot_keeps_identity_and_collections(tmp_path):
    raw = {
        "schema": st.SCHEMA,
        "room_code": "ROOM",
        "gm_token": "tok",
        "party": [{"pc_id": "pc_1", "name": "Vex", "player_label": "Sam", "hearts_max": 3, "hearts": 2}],
        "join_requests": [{"device_token": "dev-9", "name": "Ghost"}],
    }
    (tmp_path / st._SNAPSHOT_NAME).write_text(json.dumps(raw), encoding="utf-8")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state["room_code"] == "ROOM" and state["gm_token"] == "tok"
    assert state["party"] == raw["party"]
    assert state["join_requests"] == raw["join_requests"]
    assert reason is None


def test_snapshot_unknown_keys_stripped(tmp_path):
    s = st.new_state("ROOM", "tok")
    item = st.new_item("Ring", "common", "+1", "glows")
    item["minted"] = False  # fossil from an older build
    s["loot"].append(item)
    s["legacy_top_level"] = {"junk": True}
    st.save_snapshot(s, str(tmp_path))

    loaded, _ = st.load_snapshot(str(tmp_path))
    assert "legacy_top_level" not in loaded
    assert "minted" not in loaded["loot"][0]
    assert "minted" not in json.dumps(loaded)  # fossils never ride a broadcast again


def test_bom_snapshot_loads(tmp_path):
    # a user peeked at state.json in Notepad — the BOM must not nuke the session
    s = st.new_state("ROOM", "tok")
    st.save_snapshot(s, str(tmp_path))
    raw = (tmp_path / st._SNAPSHOT_NAME).read_bytes()
    (tmp_path / st._SNAPSHOT_NAME).write_bytes(b"\xef\xbb\xbf" + raw)
    state, reason = st.load_snapshot(str(tmp_path))
    assert state is not None and reason is None


def test_empty_snapshot_disclosed(tmp_path):
    (tmp_path / st._SNAPSHOT_NAME).write_bytes(b"")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state is None
    assert reason and "unreadable" in reason


def test_corrupt_main_falls_back_to_bak(tmp_path):
    s1 = st.new_state("ROOM1", "tok1")
    st.save_snapshot(s1, str(tmp_path))
    s2 = st.new_state("ROOM2", "tok2")
    st.save_snapshot(s2, str(tmp_path))  # bak = s1, main = s2
    (tmp_path / st._SNAPSHOT_NAME).write_text("{not json", encoding="utf-8")

    state, reason = st.load_snapshot(str(tmp_path))
    assert state is not None and state["room_code"] == "ROOM1"
    assert reason and "backup" in reason and "unreadable" in reason


def test_missing_main_falls_back_to_bak(tmp_path):
    s1 = st.new_state("ROOM1", "tok1")
    st.save_snapshot(s1, str(tmp_path))
    st.save_snapshot(st.new_state("ROOM2", "tok2"), str(tmp_path))  # bak = s1
    (tmp_path / st._SNAPSHOT_NAME).unlink()  # main gone, .bak remains

    state, reason = st.load_snapshot(str(tmp_path))
    assert state is not None and state["room_code"] == "ROOM1"
    assert reason and "backup" in reason and "missing" in reason


def test_non_utf8_snapshot_disclosed(tmp_path):
    (tmp_path / st._SNAPSHOT_NAME).write_bytes(b"\x80\x81\x82 garbage")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state is None
    assert reason and "unreadable" in reason


def test_corrupt_snapshot_returns_none(tmp_path):
    (tmp_path / st._SNAPSHOT_NAME).write_text("{not json", encoding="utf-8")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state is None
    assert reason and "unreadable" in reason


def test_wrong_schema_returns_none(tmp_path):
    (tmp_path / st._SNAPSHOT_NAME).write_text(json.dumps({"schema": "other/v9"}), encoding="utf-8")
    state, reason = st.load_snapshot(str(tmp_path))
    assert state is None
    assert reason and "snapshot" in reason


def test_missing_snapshot_returns_none_silently(tmp_path):
    # no snapshot at all is a normal fresh start — no disclosure needed
    assert st.load_snapshot(str(tmp_path)) == (None, None)


def test_clear_snapshot_removes_all_generations(tmp_path):
    s = st.new_state("ROOM", "tok")
    st.save_snapshot(s, str(tmp_path))
    st.save_snapshot(s, str(tmp_path))  # second save creates the .bak
    assert (tmp_path / (st._SNAPSHOT_NAME + ".bak")).exists()
    st.clear_snapshot(str(tmp_path))
    assert st.load_snapshot(str(tmp_path)) == (None, None)
    assert os.listdir(tmp_path) == []  # main, .tmp and .bak all gone
    st.clear_snapshot(str(tmp_path))  # idempotent


def test_load_reason_reaches_the_app(tmp_path):
    from server.app import create_app

    (tmp_path / st._SNAPSHOT_NAME).write_text("{not json", encoding="utf-8")
    app = create_app(str(tmp_path))
    assert app.load_reason and "unreadable" in app.load_reason

    app_fresh = create_app(str(tmp_path), fresh=True)
    assert app_fresh.load_reason is None


def test_banner_discloses_the_fallback_exactly_once(tmp_path):
    from run import banner_lines
    from server.app import create_app

    (tmp_path / st._SNAPSHOT_NAME).write_text("{not json", encoding="utf-8")
    app = create_app(str(tmp_path))
    lines = banner_lines(app.state_model, 8770, None, app.load_reason, str(tmp_path))
    notes = [ln for ln in lines if "NOTE: previous" in ln]
    assert len(notes) == 1 and "unreadable" in notes[0]

    clean_app = create_app(str(tmp_path), fresh=True)
    clean_lines = banner_lines(clean_app.state_model, 8770, None, clean_app.load_reason, str(tmp_path))
    assert not any("NOTE: previous" in ln for ln in clean_lines)
