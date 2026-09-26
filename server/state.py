"""Session state model for the table companion.

The state is a plain JSON-safe dict (one room per server process, per the
design: "one room, one server, done"). It lives in memory; every mutation
bumps ``version`` and is snapshotted to disk so a crash mid-session costs
nothing. Snapshots are ephemeral session scratch, never canon.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

SCHEMA = "table-companion/v0"
LOG_CAP = 200

# unambiguous room-code alphabet (no 0/O/1/I)
_ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def id4(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(3)}"


def gen_room_code() -> str:
    return "".join(secrets.choice(_ROOM_ALPHABET) for _ in range(4))


def now() -> float:
    return time.time()


def new_state(room_code: str, gm_token: str, session_id: str | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "version": 1,
        "room_code": room_code,
        "gm_token": gm_token,
        "session_id": session_id or datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M"),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "title": "Untitled session",
        "targets": {"default": 12, "scene": 14},
        "timers": [],
        "party": [],
        "npcs": [],
        "loot": [],
        "join_requests": [],
        # device_token -> {"pc_id": ..., "player_name": ...}
        "bindings": {},
        "log": [],  # {ts, audience: "all"|"gm", actor, text}
        "milestones": [],  # {pc_id, reason, ts}
        "alarm": None,  # {"timer_id": ...} while an expired timer is ringing
    }


def add_log(state: dict, actor: str, text: str, audience: str = "all") -> None:
    state["log"].append(
        {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "audience": audience,
            "actor": actor,
            "text": text,
        }
    )
    if len(state["log"]) > LOG_CAP:
        del state["log"][: len(state["log"]) - LOG_CAP]


def find_party(state: dict, pc_id: str) -> dict | None:
    return next((p for p in state["party"] if p["pc_id"] == pc_id), None)


def find_item(state: dict, item_id: str) -> dict | None:
    return next((i for i in state["loot"] if i["item_id"] == item_id), None)


def find_timer(state: dict, timer_id: str) -> dict | None:
    return next((t for t in state["timers"] if t["timer_id"] == timer_id), None)


def find_npc(state: dict, npc_id: str) -> dict | None:
    return next((n for n in state["npcs"] if n["npc_id"] == npc_id), None)


def new_timer(label: str, kind: str, duration_s: int | None, rounds: int | None) -> dict:
    return {
        "timer_id": id4("tm"),
        "label": label,
        "kind": kind,  # "alarm" (real time) | "rounds" (GM ticks per round)
        "duration_s": duration_s,
        "rounds_total": rounds,
        "rounds_left": rounds,
        # server-stamped wall clock (time.time()); clients render the countdown
        # locally from this — never trust the client clock
        "started_at": None,
        "elapsed_before_pause": 0.0,
        "status": "idle",  # idle | running | paused | done
    }


def new_pc(name: str, player_label: str, hearts_max: int) -> dict:
    return {
        "pc_id": id4("pc"),
        "name": name,
        "player_label": player_label,
        "hearts_max": hearts_max,
        "hearts": hearts_max,
        "inventory": [],
    }


def new_npc(name: str, hearts_max: float, effort_die: str, abilities: list[str], visible: bool) -> dict:
    return {
        "npc_id": id4("npc"),
        "name": name,
        "hearts_max": hearts_max,
        "hearts": hearts_max,
        "effort_die": effort_die,
        "abilities": abilities,
        "visible": visible,
    }


def new_item(name: str, tier: str, bonus: str, description: str, minted: bool = False) -> dict:
    return {
        "item_id": id4("it"),
        "name": name,
        "tier": tier,
        "bonus": bonus,
        "description": description,
        "claimed_by": None,  # pc_id once claimed/assigned
        "minted": minted,  # minted at the table vs. prepped
    }


def check_timers(state: dict, now_s: float) -> bool:
    """Resolve alarm-timer expiry. Returns True if anything changed.

    Pure function of (state, now) so tests can drive it without wall-clock
    sleeps; also called on every action so expiry lands on the next broadcast
    even if the watcher loop is between ticks.
    """
    changed = False
    for t in state["timers"]:
        if (
            t["kind"] == "alarm"
            and t["status"] == "running"
            and t["started_at"] is not None
            and t["duration_s"] is not None
            and now_s - t["started_at"] >= t["duration_s"]
        ):
            t["status"] = "done"
            state["alarm"] = {"timer_id": t["timer_id"], "label": t["label"]}
            add_log(state, "timer", f"⏰ {t['label']} — time!")
            changed = True
    return changed


# ---------------------------------------------------------------------------
# per-recipient views: the server never sends a player more than it should see
# ---------------------------------------------------------------------------


def _player_view(state: dict, pc_id: str) -> dict:
    view = {
        "schema": state["schema"],
        "version": state["version"],
        "room_code": state["room_code"],
        "session_id": state["session_id"],
        "title": state["title"],
        "targets": state["targets"],
        "timers": state["timers"],
        "loot": [i for i in state["loot"]],
        "npcs": [n for n in state["npcs"] if n["visible"]],
        "log": [e for e in state["log"] if e["audience"] == "all"],
        "milestones": [m for m in state["milestones"] if m["pc_id"] == pc_id],
        "alarm": state["alarm"],
        "you": {"pc_id": pc_id},
        "party": [
            # hearts are public at the table; only secret material is stripped
            {"pc_id": p["pc_id"], "name": p["name"], "player_label": p["player_label"],
             "hearts": p["hearts"], "hearts_max": p["hearts_max"]}
            for p in state["party"]
        ],
    }
    return view


def _pending_view(state: dict) -> dict:
    return {
        "schema": state["schema"],
        "version": state["version"],
        "room_code": state["room_code"],
        "title": state["title"],
        "status": "pending",
        "party": [
            {"pc_id": p["pc_id"], "name": p["name"], "player_label": p["player_label"]}
            for p in state["party"]
        ],
    }


def _gm_view(state: dict) -> dict:
    view = dict(state)
    view.pop("gm_token", None)  # the token never rides a broadcast
    return view


def view_for(state: dict, role: str, pc_id: str | None = None, device_token: str | None = None) -> dict:
    if role == "gm":
        return _gm_view(state)
    if role == "player" and pc_id:
        return _player_view(state, pc_id)
    return _pending_view(state)


# ---------------------------------------------------------------------------
# snapshot persistence: one atomic JSON file, restorable on boot
# ---------------------------------------------------------------------------

_SNAPSHOT_NAME = "state.json"


def snapshot_path(data_dir: str) -> str:
    return os.path.join(data_dir, _SNAPSHOT_NAME)


def save_snapshot(state: dict, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = snapshot_path(data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_snapshot(data_dir: str) -> dict | None:
    path = snapshot_path(data_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        # a torn snapshot must never keep the table from starting
        return None
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        return None
    return state


def clear_snapshot(data_dir: str) -> None:
    path = snapshot_path(data_dir)
    if os.path.exists(path):
        os.remove(path)


def sanitize_name(s: str, cap: int = 60) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()[:cap]
