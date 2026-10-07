"""Role-gated action vocabulary.

Every state mutation flows through :func:`apply_action`. The function mutates
the state dict in place; the caller is responsible for bumping the version,
snapshotting, and broadcasting on success.

Roles: ``gm`` does everything; a player acts only through their bound
``pc_id`` and only via the player_* actions. Anything else raises ActionError.
"""

from __future__ import annotations

import math

from . import state as st

TIERS = ("common", "uncommon", "rare", "epic")
EFFORT_DICE = ("d4", "d6", "d8", "d10", "d12")


class ActionError(Exception):
    """Rejected action — message is safe to show at the table."""


def _need(args: dict, key: str) -> object:
    v = args.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ActionError(f"missing '{key}'")
    return v


def _long_form(text: str, cap: int) -> str:
    """Long-form fields the GM composed deliberately: over-cap is an error,
    not a silent mid-word clip (names/labels still clip — ticket 44)."""
    if len(text) > cap:
        raise ActionError(f"that text is too long (max {cap} characters)")
    return st.sanitize_name(text, cap)


def _need_str(args: dict, key: str) -> str:
    """A required field that must genuinely be a string — str() of a dict or
    number would render Python repr into table-visible text."""
    v = _need(args, key)
    if not isinstance(v, str):
        raise ActionError(f"'{key}' must be a string")
    return v


def _opt_str(args: dict, key: str) -> str | None:
    """Optional string field for update handlers: absent → None (no change);
    null or non-string → ActionError. str(None) must never become the literal
    "None" in committed state (ticket 36)."""
    if key not in args:
        return None
    v = args[key]
    if v is None:
        raise ActionError(f"'{key}' cannot be null")
    if not isinstance(v, str):
        raise ActionError(f"'{key}' must be a string")
    return v


def _opt_int(args: dict, key: str) -> int | None:
    """Optional integer field: absent → None; null, bool, or non-int →
    ActionError. isinstance(True, int) is True in Python, so bools must be
    rejected explicitly or `hearts_max: true` lands in state (ticket 36)."""
    if key not in args:
        return None
    v = args[key]
    if v is None:
        raise ActionError(f"'{key}' cannot be null")
    if isinstance(v, bool) or not isinstance(v, int):
        raise ActionError(f"'{key}' must be an integer")
    return v


def _int_arg(args: dict, key: str, default: int) -> int:
    """Integer for add handlers with a default; still rejects null/bool."""
    v = _opt_int(args, key)
    return default if v is None else v


def _opt_bool(args: dict, key: str, default: bool) -> bool:
    """Disclosure flags are strict booleans — bool("false") is True, so a
    truthy string must never flip visibility/audience (ticket 36)."""
    v = args.get(key, default)
    if not isinstance(v, bool):
        raise ActionError(f"'{key}' must be true or false")
    return v


def _abilities(args: dict, key: str = "abilities") -> list[str]:
    if key not in args:
        return []
    val = args[key]
    if val is None:
        raise ActionError(f"'{key}' cannot be null")
    if not isinstance(val, list) or not all(isinstance(a, str) for a in val):
        raise ActionError(f"'{key}' must be a list of strings")
    return [st.sanitize_name(a, 60) for a in val if a.strip()][:6]


def _finite_float(v, key: str) -> float:
    """Convert a validated number to float: JSON ints are arbitrary-precision,
    so float(10**400) raises OverflowError — that must be an ActionError too."""
    try:
        f = float(v)
    except OverflowError:
        raise ActionError(f"'{key}' must be a finite number")
    if not math.isfinite(f):
        raise ActionError(f"'{key}' must be a finite number")
    return f


def _need_number(args: dict, key: str) -> float:
    """A required number that is validated, not coerced: float("abc") and
    float(True) must raise ActionError, never ValueError, and NaN/Infinity
    must never reach state math (ticket 32)."""
    v = _need(args, key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ActionError(f"'{key}' must be a number")
    return _finite_float(v, key)


def _need_timer(state: dict, args: dict) -> dict:
    t = st.find_timer(state, str(_need(args, "timer_id")))
    if t is None:
        raise ActionError("no such timer")
    return t


def _need_pc(state: dict, args: dict) -> dict:
    pc = st.find_party(state, str(_need(args, "pc_id")))
    if pc is None:
        raise ActionError("no such pc")
    return pc


def _need_npc(state: dict, args: dict) -> dict:
    npc = st.find_npc(state, str(_need(args, "npc_id")))
    if npc is None:
        raise ActionError("no such npc")
    return npc


def _need_item(state: dict, args: dict) -> dict:
    item = st.find_item(state, str(_need(args, "item_id")))
    if item is None:
        raise ActionError("no such item")
    return item


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _shift_hearts(current: float, maximum: float, delta: float) -> float:
    return round(_clamp(current + delta, 0.0, maximum), 2)


def _drop_alarm(alarm, timer_id: str):
    """Remove a timer's ringing alarm (if any); None when nothing rings."""
    if not alarm:
        return alarm
    return [a for a in alarm if a["timer_id"] != timer_id] or None


def _require_unbound(state: dict, pc_id: str) -> None:
    for tok, b in state["bindings"].items():
        if b["pc_id"] == pc_id:
            raise ActionError(f"{st.find_party(state, pc_id)['name']} is already seated on another device")


# ---------------------------------------------------------------------------
# gm actions
# ---------------------------------------------------------------------------


def _gm_action(state: dict, actor: str, action: str, args: dict) -> None:
    if action == "set_title":
        # empty is a legitimate title (the GM clears the field) — only a
        # missing/non-string argument is rejected (ticket 50)
        raw = args.get("title")
        if raw is None:
            raw = ""
        if not isinstance(raw, str):
            raise ActionError("'title' must be a string")
        state["title"] = st.sanitize_name(raw, 80)

    elif action == "set_targets":
        # two shapes: absolute {default, scene}, or the TN card's delta
        # {which, delta} — deltas can't lose fast taps (ticket 50)
        if "which" in args or "delta" in args:
            which = _need(args, "which")
            if which not in ("default", "scene"):
                raise ActionError("'which' must be default or scene")
            delta = _need_number(args, "delta")
            if delta != int(delta):
                raise ActionError("'delta' must be an integer")
            delta = int(delta)
            other = "scene" if which == "default" else "default"
            new = int(_clamp(int(state["targets"].get(which, 12)) + delta, 2, 30))
            state["targets"] = {**state["targets"], other: int(state["targets"].get(other, 14)), which: new}
        else:
            d = _opt_int(args, "default")
            s = _opt_int(args, "scene")
            if d is None:
                raise ActionError("missing 'default'")
            if s is None:
                raise ActionError("missing 'scene'")
            if not (2 <= d <= 30 and 2 <= s <= 30):
                raise ActionError("targets must be 2..30")
            state["targets"] = {"default": d, "scene": s}

    elif action == "timer_add":
        kind = _need(args, "kind")
        if kind not in ("alarm", "rounds"):
            raise ActionError("timer kind must be alarm or rounds")
        label = st.sanitize_name(_need_str(args, "label"), 60)
        duration = _opt_int(args, "duration_s")
        rounds = _opt_int(args, "rounds")
        if kind == "alarm":
            if duration is None or not (1 <= duration <= 24 * 3600):
                raise ActionError("alarm needs duration_s (1..86400)")
            rounds = None
        else:
            if rounds is None or not (1 <= rounds <= 99):
                raise ActionError("rounds timer needs rounds (1..99)")
            duration = None
        state["timers"].append(st.new_timer(label, kind, duration, rounds))

    elif action == "timer_update":
        # validate everything, then mutate: a rejected update must leave the
        # timer exactly as it was (ticket 32)
        t = _need_timer(state, args)
        label = _opt_str(args, "label")
        d = _opt_int(args, "duration_s")
        r = _opt_int(args, "rounds")
        # kind-mismatched fields are a client bug — reject, never silently no-op
        if d is not None and t["kind"] != "alarm":
            raise ActionError("duration_s belongs to an alarm timer")
        if r is not None and t["kind"] != "rounds":
            raise ActionError("rounds belongs to a rounds timer")
        if d is not None and not (1 <= d <= 24 * 3600):
            raise ActionError("duration_s must be 1..86400")
        if r is not None and not (1 <= r <= 99):
            raise ActionError("rounds must be 1..99")
        if label is not None:
            t["label"] = st.sanitize_name(label, 60) or t["label"]
        if d is not None:
            t["duration_s"] = d
            if t["status"] != "running":
                t["status"] = "idle"
                t["started_at"] = None
                t["elapsed_before_pause"] = 0.0
            # re-timing a rung-out alarm clears its stale ring, same rule as
            # the rounds branch and timer_reset (ticket 42)
            state["alarm"] = _drop_alarm(state["alarm"], t["timer_id"])
        if r is not None:
            # re-rounding a rung-out timer means "give it more rounds" — the
            # ringing alarm must go with it (ticket 42)
            t["rounds_total"] = r
            t["rounds_left"] = r
            t["status"] = "idle"
            state["alarm"] = _drop_alarm(state["alarm"], t["timer_id"])

    elif action == "timer_delete":
        tid = str(_need(args, "timer_id"))
        state["timers"] = [t for t in state["timers"] if t["timer_id"] != tid]
        state["alarm"] = _drop_alarm(state["alarm"], tid)

    elif action == "timer_start":
        t = _need_timer(state, args)
        if t["kind"] != "alarm":
            raise ActionError("rounds timers advance with timer_tick, not start")
        if t["status"] == "running":
            raise ActionError("timer already running")
        if t["status"] == "paused":
            t["started_at"] = st.now() - t["elapsed_before_pause"]
        else:
            t["started_at"] = st.now()
        t["status"] = "running"
        # restarting a timer whose alarm is still ringing clears the ring
        # (same rule timer_reset follows — ticket 42)
        state["alarm"] = _drop_alarm(state["alarm"], t["timer_id"])

    elif action == "timer_pause":
        t = _need_timer(state, args)
        if t["status"] != "running":
            raise ActionError("timer is not running")
        t["elapsed_before_pause"] = st.now() - t["started_at"]
        t["status"] = "paused"

    elif action == "timer_reset":
        t = _need_timer(state, args)
        t["status"] = "idle"
        t["started_at"] = None
        t["elapsed_before_pause"] = 0.0
        if t["kind"] == "rounds":
            t["rounds_left"] = t["rounds_total"]
        state["alarm"] = _drop_alarm(state["alarm"], t["timer_id"])

    elif action == "timer_tick":
        t = _need_timer(state, args)
        if t["kind"] != "rounds":
            raise ActionError("no such rounds timer")
        if t["rounds_left"] <= 0:
            raise ActionError("timer already at zero — reset it")
        t["rounds_left"] -= 1
        if t["rounds_left"] == 0:
            t["status"] = "done"
            state["alarm"] = state["alarm"] or []
            state["alarm"].append({"timer_id": t["timer_id"], "label": t["label"]})
            st.add_log(state, "timer", f"⏰ {t['label']} — time!")

    elif action == "alarm_dismiss":
        state["alarm"] = None

    elif action == "pc_add":
        name = st.sanitize_name(_need_str(args, "name"), 40)
        if not name:
            raise ActionError("pc needs a name")
        hearts = _int_arg(args, "hearts_max", 3)
        if not (1 <= hearts <= 20):
            raise ActionError("hearts_max must be 1..20")
        player_label = _opt_str(args, "player_label")
        state["party"].append(
            st.new_pc(name, st.sanitize_name(player_label or "", 40), hearts)
        )

    elif action == "pc_update":
        # validate everything, then mutate (ticket 32)
        pc = _need_pc(state, args)
        name = _opt_str(args, "name")
        player_label = _opt_str(args, "player_label")
        hm = _opt_int(args, "hearts_max")
        if hm is not None and not (1 <= hm <= 20):
            raise ActionError("hearts_max must be 1..20")
        if name is not None:
            pc["name"] = st.sanitize_name(name, 40) or pc["name"]
        if player_label is not None:
            pc["player_label"] = st.sanitize_name(player_label, 40)
        if hm is not None:
            pc["hearts_max"] = hm
            if pc["hearts"] > hm:
                lost = round(pc["hearts"] - hm, 2)
                st.add_log(state, actor, f"{pc['name']} loses {lost} hearts (max lowered to {hm})", audience="gm")
            pc["hearts"] = min(pc["hearts"], hm)

    elif action == "pc_delete":
        pc = _need_pc(state, args)  # a stale id is "no such pc", not a no-op
        pc_id = pc["pc_id"]
        state["party"] = [p for p in state["party"] if p["pc_id"] != pc_id]
        state["bindings"] = {k: b for k, b in state["bindings"].items() if b["pc_id"] != pc_id}
        for item in state["loot"]:
            if item["claimed_by"] == pc_id:
                item["claimed_by"] = None
                st.add_log(state, actor, f"{item['name']} returned to the pool ({pc['name']} left)", audience="gm")

    elif action == "pc_hearts":
        pc = _need_pc(state, args)
        pc["hearts"] = _shift_hearts(pc["hearts"], pc["hearts_max"], _need_number(args, "delta"))

    elif action == "npc_add":
        name = st.sanitize_name(_need_str(args, "name"), 40)
        if not name:
            raise ActionError("npc needs a name")
        hearts = args.get("hearts_max", 1)
        if isinstance(hearts, bool) or not isinstance(hearts, (int, float)):
            raise ActionError("'hearts_max' must be a number")
        hearts = _finite_float(hearts, "hearts_max")
        if not (0.5 <= hearts <= 40):
            raise ActionError("hearts_max must be 0.5..40")
        die = str(args.get("effort_die", "d6"))
        if die not in EFFORT_DICE:
            raise ActionError("effort_die must be one of " + ", ".join(EFFORT_DICE))
        state["npcs"].append(st.new_npc(name, hearts, die, _abilities(args), _opt_bool(args, "visible", False)))

    elif action == "npc_update":
        # validate everything, then mutate (ticket 32)
        npc = _need_npc(state, args)
        name = _opt_str(args, "name")
        hearts = None
        if "hearts_max" in args:
            raw = args["hearts_max"]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ActionError("'hearts_max' must be a number")
            hearts = _finite_float(raw, "hearts_max")
            if not (0.5 <= hearts <= 40):
                raise ActionError("hearts_max must be 0.5..40")
        if "effort_die" in args and args["effort_die"] not in EFFORT_DICE:
            raise ActionError("bad effort_die")
        abilities = _abilities(args) if "abilities" in args else None
        if name is not None:
            npc["name"] = st.sanitize_name(name, 40) or npc["name"]
        if hearts is not None:
            npc["hearts_max"] = hearts
            if npc["hearts"] > hearts:
                lost = round(npc["hearts"] - hearts, 2)
                st.add_log(state, actor, f"{npc['name']} loses {lost} hearts (max lowered to {hearts})", audience="gm")
            npc["hearts"] = min(npc["hearts"], hearts)
        if "effort_die" in args:
            npc["effort_die"] = args["effort_die"]
        if abilities is not None:
            npc["abilities"] = abilities

    elif action == "npc_delete":
        nid = str(_need(args, "npc_id"))
        state["npcs"] = [n for n in state["npcs"] if n["npc_id"] != nid]

    elif action == "npc_reveal":
        npc = _need_npc(state, args)
        npc["visible"] = _opt_bool(args, "visible", True)
        st.add_log(
            state, actor, f"{npc['name']} {'takes the stage' if npc['visible'] else 'steps back into the shadows'}"
        )

    elif action == "npc_hearts":
        npc = _need_npc(state, args)
        npc["hearts"] = _shift_hearts(npc["hearts"], npc["hearts_max"], _need_number(args, "delta"))

    elif action == "loot_add":
        name = st.sanitize_name(_need_str(args, "name"), 60)
        if not name:
            raise ActionError("item needs a name")
        tier = str(args.get("tier", "common"))
        if tier not in TIERS:
            raise ActionError("tier must be one of " + ", ".join(TIERS))
        state["loot"].append(
            st.new_item(
                name,
                tier,
                st.sanitize_name(_opt_str(args, "bonus") or "", 60),
                _long_form(_opt_str(args, "description") or "", 200),
            )
        )

    elif action == "loot_update":
        # validate everything, then mutate (ticket 32)
        item = _need_item(state, args)
        name = _opt_str(args, "name")
        bonus = _opt_str(args, "bonus")
        description = _opt_str(args, "description")
        if "tier" in args and args["tier"] not in TIERS:
            raise ActionError("bad tier")
        if description is not None:
            description = _long_form(description, 200)
        if name is not None:
            item["name"] = st.sanitize_name(name, 60) or item["name"]
        if "tier" in args:
            item["tier"] = args["tier"]
        if bonus is not None:
            item["bonus"] = st.sanitize_name(bonus, 60)
        if description is not None:
            item["description"] = description

    elif action == "loot_delete":
        iid = str(_need(args, "item_id"))
        state["loot"] = [i for i in state["loot"] if i["item_id"] != iid]

    elif action == "loot_assign":
        item = _need_item(state, args)
        pc_id = args.get("pc_id")
        if pc_id is None:
            if item["claimed_by"] is None:
                raise ActionError("item is already in the pool")
            owner = st.find_party(state, item["claimed_by"])
            item["claimed_by"] = None
            st.add_log(state, actor, f"{item['name']} recalled from {owner['name'] if owner else 'a gone character'}")
        else:
            pc = st.find_party(state, str(pc_id))
            if pc is None:
                raise ActionError("no such pc")
            item["claimed_by"] = pc["pc_id"]
            st.add_log(state, actor, f"{item['name']} handed to {pc['name']}")

    elif action == "approve_join":
        token = str(_need(args, "device_token"))
        req = next((r for r in state["join_requests"] if r["device_token"] == token), None)
        if req is None and not st.is_rejected(state, token):
            raise ActionError("no such join request")
        pc = _need_pc(state, args)
        _require_unbound(state, pc["pc_id"])
        # only consume the request once every validation passed — a failed
        # approve must leave it retryable
        if req is not None:
            st.drop_join_request(state, token)
        state["rejections"] = [r for r in state["rejections"] if r["device_token"] != token]
        state["bindings"][token] = {"pc_id": pc["pc_id"]}
        st.add_log(state, actor, f"{req['name'] if req else 'A returning player'} sat down as {pc['name']}")

    elif action == "reject_join":
        token = str(_need(args, "device_token"))
        if state["bindings"].get(token) is not None:
            raise ActionError("that device is seated — delete the character first")
        req = next((r for r in state["join_requests"] if r["device_token"] == token), None)
        st.drop_join_request(state, token)
        if not st.is_rejected(state, token):
            state["rejections"].append({"device_token": token, "name": req["name"] if req else ""})
        if req:
            st.add_log(state, actor, f"turned {req['name']} away", audience="gm")

    elif action == "milestone_add":
        pc = _need_pc(state, args)
        reason = _long_form(_need_str(args, "reason"), 140)
        state["milestones"].append(
            {"id": st.id4("ms"), "pc_id": pc["pc_id"], "pc_name": pc["name"], "reason": reason, "ts": st.now_iso()}
        )
        st.add_log(state, actor, f"{pc['name']} earned a milestone — {reason}")

    elif action == "milestone_delete":
        # delete by stable id, not index — index deletes mis-delete under
        # render/echo skew (ticket 50)
        mid = str(_need(args, "id"))
        before = len(state["milestones"])
        state["milestones"] = [m for m in state["milestones"] if m.get("id") != mid]
        if len(state["milestones"]) == before:
            raise ActionError("no such milestone")

    elif action == "log_note":
        text = _long_form(_need_str(args, "text"), 200)
        audience = "all" if _opt_bool(args, "share", False) else "gm"
        st.add_log(state, actor, text, audience=audience)

    elif action == "starter_load":
        from .content import load_pack

        added = load_pack(state, str(_need(args, "pack")))
        st.add_log(state, actor, f"loaded starter content: {added}", audience="gm")

    elif action == "session_reset":
        keep = (state["room_code"], state["gm_token"])
        fresh = st.new_state(keep[0], keep[1])
        state.clear()
        state.update(fresh)

    else:
        raise ActionError(f"unknown action '{action}'")


# ---------------------------------------------------------------------------
# player actions (scoped to the caller's bound pc)
# ---------------------------------------------------------------------------


def _player_action(state: dict, actor: str, pc_id: str, action: str, args: dict) -> None:
    pc = st.find_party(state, pc_id)
    if pc is None:  # binding references a deleted pc
        raise ActionError("your character no longer exists — ask the GM for a new seat")

    if action == "player_claim":
        item = _need_item(state, args)
        if item["claimed_by"] is not None:
            raise ActionError("already claimed")
        item["claimed_by"] = pc_id
        st.add_log(state, actor, f"{pc['name']} claimed {item['name']}")

    elif action == "player_return":
        item = st.find_item(state, str(_need(args, "item_id")))
        if item is None or item["claimed_by"] != pc_id:
            raise ActionError("that item is not in your pack")
        item["claimed_by"] = None
        st.add_log(state, actor, f"{pc['name']} tossed {item['name']} back into the pool")

    elif action == "player_hearts":
        pc["hearts"] = _shift_hearts(pc["hearts"], pc["hearts_max"], _need_number(args, "delta"))

    else:
        raise ActionError(f"unknown player action '{action}'")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def apply_action(state: dict, role: str, actor: str, action: str, args: dict | None = None,
                 pc_id: str | None = None) -> None:
    """Apply one action. Raises ActionError on rejection; mutates on success."""
    args = args or {}
    if role == "gm":
        _gm_action(state, actor, action, args)
    elif role == "player":
        if pc_id is None:
            raise ActionError("not seated yet")
        _player_action(state, actor, pc_id, action, args)
    else:
        raise ActionError("unauthorized")
