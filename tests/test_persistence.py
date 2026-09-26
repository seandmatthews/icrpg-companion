import json
import os

from server import state as st


def test_snapshot_round_trip(tmp_path):
    s = st.new_state("ROOM", "tok")
    st.add_log(s, "GM", "hello")
    s["party"].append(st.new_pc("Vex", "Sam", 3))
    st.save_snapshot(s, str(tmp_path))

    loaded = st.load_snapshot(str(tmp_path))
    assert loaded == s
    assert loaded["room_code"] == "ROOM"


def test_snapshot_write_is_atomic(tmp_path):
    s = st.new_state("ROOM", "tok")
    st.save_snapshot(s, str(tmp_path))
    names = os.listdir(tmp_path)
    assert names == [st._SNAPSHOT_NAME]  # no .tmp litter


def test_corrupt_snapshot_returns_none(tmp_path):
    (tmp_path / st._SNAPSHOT_NAME).write_text("{not json", encoding="utf-8")
    assert st.load_snapshot(str(tmp_path)) is None


def test_wrong_schema_returns_none(tmp_path):
    (tmp_path / st._SNAPSHOT_NAME).write_text(json.dumps({"schema": "other/v9"}), encoding="utf-8")
    assert st.load_snapshot(str(tmp_path)) is None


def test_missing_snapshot_returns_none(tmp_path):
    assert st.load_snapshot(str(tmp_path)) is None


def test_clear_snapshot(tmp_path):
    st.save_snapshot(st.new_state("ROOM", "tok"), str(tmp_path))
    st.clear_snapshot(str(tmp_path))
    assert st.load_snapshot(str(tmp_path)) is None
    assert st.clear_snapshot(str(tmp_path)) is None  # idempotent
