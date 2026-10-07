"""Session state model for the table companion.

The state is a plain JSON-safe dict (one room per server process, per the
design: "one room, one server, done"). It lives in memory; every mutation
bumps ``version`` and is snapshotted to disk so a crash mid-session costs
nothing. Snapshots are ephemeral session scratch, never canon.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
import unicodedata
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
        # devices the GM turned away: a reload must not re-knock (ticket 33).
        # The name is kept so the GM console can offer to seat them again.
        "rejections": [],
        # device_token -> {"pc_id": ...}
        "bindings": {},
        "log": [],  # {ts, audience: "all"|"gm", actor, text}
        "milestones": [],  # {pc_id, pc_name, reason, ts}
        "alarm": None,  # list of {"timer_id", "label"} while timers are ringing
    }


def add_log(state: dict, actor: str, text: str, audience: str = "all") -> None:
    state["log"].append(
        {
            "id": id4("lg"),  # stable key for clients (ticket 50)
            "ts": now_iso(),
            "audience": audience,
            "actor": actor,
            "text": text,
        }
    )
    if len(state["log"]) > LOG_CAP:
        del state["log"][: len(state["log"]) - LOG_CAP]


def drop_join_request(state: dict, device_token: str) -> bool:
    before = len(state["join_requests"])
    state["join_requests"] = [
        r for r in state["join_requests"] if r["device_token"] != device_token
    ]
    return len(state["join_requests"]) < before


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


def new_item(name: str, tier: str, bonus: str, description: str) -> dict:
    return {
        "item_id": id4("it"),
        "name": name,
        "tier": tier,
        "bonus": bonus,
        "description": description,
        "claimed_by": None,  # pc_id once claimed/assigned
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
            # the alarm slot is a QUEUE: two timers expiring in the same tick
            # both ring (ticket 42)
            state["alarm"] = state["alarm"] or []
            state["alarm"].append({"timer_id": t["timer_id"], "label": t["label"]})
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


def _pending_view(state: dict, rejected: bool = False) -> dict:
    view = {
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
    if rejected:
        view["rejected"] = True
    return view


def _gm_view(state: dict) -> dict:
    view = dict(state)
    view.pop("gm_token", None)  # the token never rides a broadcast
    return view


def view_for(state: dict, role: str, pc_id: str | None = None, device_token: str | None = None) -> dict:
    if role == "gm":
        return _gm_view(state)
    if role == "player" and pc_id:
        return _player_view(state, pc_id)
    rejected = device_token is not None and is_rejected(state, device_token)
    return _pending_view(state, rejected)


def is_rejected(state: dict, device_token: str) -> bool:
    return any(r["device_token"] == device_token for r in state["rejections"])


# ---------------------------------------------------------------------------
# snapshot persistence: one atomic JSON file, restorable on boot
# ---------------------------------------------------------------------------

_SNAPSHOT_NAME = "state.json"
SNAPSHOT_LOCK_NAME = ".lock"

_log = logging.getLogger("table-companion")


def snapshot_path(data_dir: str) -> str:
    return os.path.join(data_dir, _SNAPSHOT_NAME)


def save_snapshot(state: dict, data_dir: str) -> None:
    """Write the snapshot atomically. Raises on failure — the COMMIT PATH
    (hub.commit) decides whether a failure is fatal; a locked destination
    must degrade to 'session lives in memory', not kill the connection
    (ticket 46). NaN/Inf raise ValueError via allow_nan=False: browsers
    reject bare NaN, so it must never reach the wire or the disk."""
    os.makedirs(data_dir, exist_ok=True)
    path = snapshot_path(data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())  # power loss must not leave a 0-byte snapshot
    if os.path.exists(path):
        try:
            # keep one fsynced previous generation; the .bak is a second
            # belt, never a failure
            with open(path, "rb") as src, open(path + ".bak", "wb") as dst:
                dst.write(src.read())
                dst.flush()
                os.fsync(dst.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


# canonical key-sets for snapshot entries: keys outside `allowed` are fossils
# from an older build and are stripped on load; an entry missing any `required`
# key is dropped entirely (with a note) — those are the keys downstream code
# indexes directly, so a snapshot missing them must never KeyError the server
_ENTRY_SHAPE = {
    "party": (
        {"pc_id", "name", "player_label", "hearts_max", "hearts", "inventory"},
        {"pc_id", "name", "player_label", "hearts_max", "hearts"},
    ),
    "npcs": (
        {"npc_id", "name", "hearts_max", "hearts", "effort_die", "abilities", "visible"},
        {"npc_id", "name", "hearts_max", "hearts", "visible"},
    ),
    "loot": (
        {"item_id", "name", "tier", "bonus", "description", "claimed_by"},
        {"item_id", "name", "claimed_by"},
    ),
    "timers": (
        {
            "timer_id", "label", "kind", "duration_s", "rounds_total",
            "rounds_left", "started_at", "elapsed_before_pause", "status",
        },
        {
            "timer_id", "label", "kind", "duration_s", "rounds_total",
            "rounds_left", "started_at", "elapsed_before_pause", "status",
        },
    ),
    "join_requests": ({"device_token", "name"}, {"device_token", "name"}),
    "rejections": ({"device_token", "name"}, {"device_token"}),
    "milestones": ({"id", "pc_id", "pc_name", "reason", "ts"}, {"pc_id"}),
}
_LOG_ALLOWED = {"id", "ts", "audience", "actor", "text"}
_LOG_REQUIRED = {"ts", "audience", "actor", "text"}


def _clean_entries(entries: list, allowed: set, required: set) -> tuple[list, int]:
    out, dropped = [], 0
    for e in entries:
        if not isinstance(e, dict) or not required.issubset(e.keys()):
            dropped += 1
            continue
        out.append({k: v for k, v in e.items() if k in allowed})
    return out, dropped


def _normalize_state(raw: dict) -> tuple[dict, list[str]]:
    """Rebuild a snapshot against the current new_state() template: backfill
    missing keys, mint identity when it is gone, strip fossil keys (top level
    and per-entry), and drop entries missing required keys — an older or
    torn-but-valid snapshot must never KeyError the server later.
    Returns (state, notes) where notes are the human-readable repairs for
    the banner."""
    notes: list[str] = []
    room_code = raw.get("room_code")
    if not isinstance(room_code, str) or not room_code:
        room_code = gen_room_code()
        notes.append("room code was missing — minted a new one")
    gm_token = raw.get("gm_token")
    if not isinstance(gm_token, str) or not gm_token:
        gm_token = secrets.token_urlsafe(12)
        notes.append("GM key was missing — minted a new one (printed above)")
    session_id = raw.get("session_id")
    if "session_id" in raw and not isinstance(session_id, str):
        notes.append("session id was malformed — regenerated")
        session_id = None
    state = new_state(room_code, gm_token, session_id)

    if isinstance(raw.get("title"), str):
        state["title"] = raw["title"]  # empty is legitimate (ticket 50)
    elif "title" in raw:
        notes.append("title was malformed — reset to the default")
    version = raw.get("version")
    if isinstance(version, int) and not isinstance(version, bool):
        state["version"] = version
    created = raw.get("created")
    if isinstance(created, str):
        state["created"] = created

    for key, want in (("targets", dict),):
        val = raw.get(key)
        if isinstance(val, want):
            state[key] = val
        elif key in raw:
            notes.append(f"{key} had the wrong type — reset")
    # alarm was a single dict before ticket 42's queue — accept both shapes
    alarm = raw.get("alarm")
    if alarm is None:
        pass
    elif isinstance(alarm, list):
        state["alarm"] = [
            a
            for a in alarm
            if isinstance(a, dict) and isinstance(a.get("timer_id"), str) and isinstance(a.get("label"), str)
        ] or None
    elif isinstance(alarm, dict) and isinstance(alarm.get("timer_id"), str):
        state["alarm"] = [alarm]
    elif "alarm" in raw:
        notes.append("alarm had the wrong type — reset")

    for key, (allowed, required) in _ENTRY_SHAPE.items():
        val = raw.get(key)
        if isinstance(val, list):
            cleaned, dropped = _clean_entries(val, allowed, required)
            state[key] = cleaned
            if dropped:
                notes.append(f"{key}: {dropped} invalid entr{'y' if dropped == 1 else 'ies'} dropped")
        elif key in raw:
            notes.append(f"{key} had the wrong type — reset")
    log = raw.get("log")
    if isinstance(log, list):
        cleaned, dropped = _clean_entries(log, _LOG_ALLOWED, _LOG_REQUIRED)
        state["log"] = cleaned
        if dropped:
            notes.append(f"log: {dropped} invalid entries dropped")
    elif "log" in raw:
        notes.append("log had the wrong type — reset")
    # pre-50 milestones/log entries carry no stable id — mint one on load
    for m in state["milestones"]:
        if not m.get("id"):
            m["id"] = id4("ms")
    for e in state["log"]:
        if not e.get("id"):
            e["id"] = id4("lg")

    bindings = raw.get("bindings")
    if isinstance(bindings, dict):
        state["bindings"] = {
            str(k): {"pc_id": v["pc_id"]}
            for k, v in bindings.items()
            if isinstance(v, dict) and isinstance(v.get("pc_id"), str)
        }
    elif "bindings" in raw:
        notes.append("bindings had the wrong type — reset")

    return state, notes


def _read_snapshot_file(path: str) -> tuple[dict | None, str | None]:
    """Returns (raw, None) on success, (None, reason) when damaged, and
    (None, None) when the file simply does not exist."""
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8-sig") as f:  # -sig: Notepad loves BOMs
            raw = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return None, f"unreadable ({type(e).__name__})"
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None, f"is not a {SCHEMA} snapshot"
    return raw, None


def load_snapshot(data_dir: str) -> tuple[dict | None, str | None]:
    """Load and normalize the session snapshot.

    Returns (state, reason): (state, None) on a clean load; (None, None)
    when no snapshot exists — a normal fresh start, nothing to disclose;
    (state/reason, ...) otherwise. The reason is always disclosed on the
    banner, never silent. A missing or damaged main snapshot falls back to
    the .bak copy of the previous save before giving up.
    """
    path = snapshot_path(data_dir)
    raw, err = _read_snapshot_file(path)
    if raw is None:
        bak_raw, _ = _read_snapshot_file(path + ".bak")
        if bak_raw is not None:
            state, notes = _normalize_state(bak_raw)
            cause = "was missing" if err is None else err
            reason = f"snapshot {cause} — restored the previous session from the backup copy"
            if notes:
                reason += "; " + "; ".join(notes)
            return state, reason
        if err is None:
            return None, None  # absent: a normal fresh start, nothing to disclose
        return None, f"snapshot {err} — starting a fresh session"
    state, notes = _normalize_state(raw)
    return state, ("; ".join(notes) if notes else None)


def lock_path(data_dir: str) -> str:
    return os.path.join(data_dir, SNAPSHOT_LOCK_NAME)


def acquire_lock(data_dir: str) -> None:
    """One server per data dir: an O_EXCL lockfile holding our pid. A lock
    from THIS process (tests re-booting the same dir) is reused; a stale one
    from a dead process can't be reliably detected on Windows, so the error
    tells the user how to recover (ticket 46)."""
    os.makedirs(data_dir, exist_ok=True)
    path = lock_path(data_dir)
    pid = str(os.getpid())
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            f.write(pid)
    except FileExistsError:
        try:
            with open(path, encoding="utf-8") as f:
                holder = f.read().strip()
        except OSError:
            holder = "?"
        if holder == pid:
            return  # ours from an earlier create_app in this process
        raise RuntimeError(
            f"another table-companion server appears to be using {data_dir} "
            f"(lock held by pid {holder}). If no other server is running, "
            f"delete {path} and start again."
        ) from None


def release_lock(data_dir: str) -> None:
    try:
        with open(lock_path(data_dir), encoding="utf-8") as f:
            if f.read().strip() != str(os.getpid()):
                return  # not ours — leave it
        os.remove(lock_path(data_dir))
    except OSError:
        pass


def clear_snapshot(data_dir: str) -> None:
    # .bak goes before main: a crash mid-clear must never leave only the old
    # generation behind to resurrect a "deleted" session. A locked file
    # (editor/AV) logs a warning instead of crashing boot (ticket 46).
    for suffix in (".tmp", ".bak", ""):
        p = snapshot_path(data_dir) + suffix
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError as e:
            # keep going: the subsequent save's os.replace will hit the same
            # lock and the commit guard degrades to "session lives in memory"
            _log.warning("could not remove %s: %s", p, e)


def sanitize_name(s: str, cap: int = 60) -> str:
    """Normalize to NFC (two renders of "Café" must be one name), drop
    control/zero-width/bidi characters (they make names look identical or
    reverse following text), then collapse whitespace (ticket 45)."""
    s = "".join(c for c in (s or "") if unicodedata.category(c) not in ("Cc", "Cf"))
    s = unicodedata.normalize("NFC", s)  # AFTER filtering: a Cf starter would block composition
    return re.sub(r"\s+", " ", s).strip()[:cap]
