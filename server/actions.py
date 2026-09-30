"""Role-gated action vocabulary.

Every state mutation flows through :func:`apply_action`. The function mutates
the state dict in place; the caller is responsible for bumping the version,
snapshotting, and broadcasting on success.

Roles: ``gm`` does everything; a player acts only through their bound
``pc_id`` and only via the player_* actions. Anything else raises ActionError.
"""

from __future__ import annotations

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


def _require_unbound(state: dict, pc_id: str) -> None:
    for tok, b in state["bindings"].items():
        if b["pc_id"] == pc_id:
            raise ActionError(f"{st.find_party(state, pc_id)['name']} is already seated on another device")


# ---------------------------------------------------------------------------
# gm actions
# ---------------------------------------------------------------------------


def _gm_action(state: dict, actor: str, action: str, args: dict) -> None:
    if action == "set_title":
        state["title"] = st.sanitize_name(str(_need(args, "title")), 80)

    elif action == "set_targets":
        d = int(_need(args, "default"))
        s = int(_need(args, "scene"))
        if not (2 <= d <= 30 and 2 <= s <= 30):
            raise ActionError("targets must be 2..30")
        state["targets"] = {"default": d, "scene": s}

    elif action == "timer_add":
        kind = _need(args, "kind")
        if kind not in ("alarm", "rounds"):
            raise ActionError("timer kind must be alarm or rounds")
        label = st.sanitize_name(str(_need(args, "label")), 60)
        duration = args.get("duration_s")
        rounds = args.get("rounds")
        if kind == "alarm":
            if not isinstance(duration, int) or not (1 <= duration <= 24 * 3600):
                raise ActionError("alarm needs duration_s (1..86400)")
            rounds = None
        else:
            if not isinstance(rounds, int) or not (1 <= rounds <= 99):
                raise ActionError("rounds timer needs rounds (1..99)")
            duration = None
        state["timers"].append(st.new_timer(label, kind, duration, rounds))

    elif action == "timer_update":
        t = _need_timer(state, args)
        if "label" in args:
            t["label"] = st.sanitize_name(str(args["label"]), 60)
        if "duration_s" in args and t["kind"] == "alarm":
            d = int(args["duration_s"])
            if not (1 <= d <= 24 * 3600):
                raise ActionError("duration_s must be 1..86400")
            t["duration_s"] = d
            if t["status"] != "running":
                t["status"] = "idle"
                t["started_at"] = None
                t["elapsed_before_pause"] = 0.0
        if "rounds" in args and t["kind"] == "rounds":
            r = int(args["rounds"])
            if not (1 <= r <= 99):
                raise ActionError("rounds must be 1..99")
            t["rounds_total"] = r
            t["rounds_left"] = r
            t["status"] = "idle"

    elif action == "timer_delete":
        tid = str(_need(args, "timer_id"))
        state["timers"] = [t for t in state["timers"] if t["timer_id"] != tid]
        if state["alarm"] and state["alarm"].get("timer_id") == tid:
            state["alarm"] = None

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

    elif action == "timer_pause":
        t = st.find_timer(state, str(_need(args, "timer_id")))
        if t is None or t["status"] != "running":
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
        if state["alarm"] and state["alarm"].get("timer_id") == t["timer_id"]:
            state["alarm"] = None

    elif action == "timer_tick":
        t = st.find_timer(state, str(_need(args, "timer_id")))
        if t is None or t["kind"] != "rounds":
            raise ActionError("no such rounds timer")
        if t["rounds_left"] <= 0:
            raise ActionError("timer already at zero — reset it")
        t["rounds_left"] -= 1
        if t["rounds_left"] == 0:
            t["status"] = "done"
            state["alarm"] = {"timer_id": t["timer_id"], "label": t["label"]}
            st.add_log(state, "timer", f"⏰ {t['label']} — time!")

    elif action == "alarm_dismiss":
        state["alarm"] = None

    elif action == "pc_add":
        name = st.sanitize_name(str(_need(args, "name")), 40)
        if not name:
            raise ActionError("pc needs a name")
        hearts = args.get("hearts_max", 3)
        if not isinstance(hearts, int) or not (1 <= hearts <= 20):
            raise ActionError("hearts_max must be 1..20")
        state["party"].append(
            st.new_pc(name, st.sanitize_name(str(args.get("player_label", "")), 40), hearts)
        )

    elif action == "pc_update":
        pc = _need_pc(state, args)
        if "name" in args:
            pc["name"] = st.sanitize_name(str(args["name"]), 40) or pc["name"]
        if "player_label" in args:
            pc["player_label"] = st.sanitize_name(str(args["player_label"]), 40)
        if "hearts_max" in args:
            hm = int(args["hearts_max"])
            if not (1 <= hm <= 20):
                raise ActionError("hearts_max must be 1..20")
            pc["hearts_max"] = hm
            pc["hearts"] = min(pc["hearts"], hm)

    elif action == "pc_delete":
        pc_id = str(_need(args, "pc_id"))
        state["party"] = [p for p in state["party"] if p["pc_id"] != pc_id]
        state["bindings"] = {k: b for k, b in state["bindings"].items() if b["pc_id"] != pc_id}
        for item in state["loot"]:
            if item["claimed_by"] == pc_id:
                item["claimed_by"] = None

    elif action == "pc_hearts":
        pc = _need_pc(state, args)
        pc["hearts"] = _shift_hearts(pc["hearts"], pc["hearts_max"], float(_need(args, "delta")))

    elif action == "npc_add":
        name = st.sanitize_name(str(_need(args, "name")), 40)
        if not name:
            raise ActionError("npc needs a name")
        hearts = float(args.get("hearts_max", 1))
        if not (0.5 <= hearts <= 40):
            raise ActionError("hearts_max must be 0.5..40")
        die = str(args.get("effort_die", "d6"))
        if die not in EFFORT_DICE:
            raise ActionError("effort_die must be one of " + ", ".join(EFFORT_DICE))
        abilities = [st.sanitize_name(str(a), 60) for a in args.get("abilities", []) if str(a).strip()][:6]
        state["npcs"].append(st.new_npc(name, hearts, die, abilities, bool(args.get("visible", False))))

    elif action == "npc_update":
        npc = _need_npc(state, args)
        if "name" in args:
            npc["name"] = st.sanitize_name(str(args["name"]), 40) or npc["name"]
        if "hearts_max" in args:
            hm = float(args["hearts_max"])
            if not (0.5 <= hm <= 40):
                raise ActionError("hearts_max must be 0.5..40")
            npc["hearts_max"] = hm
            npc["hearts"] = min(npc["hearts"], hm)
        if "effort_die" in args:
            if args["effort_die"] not in EFFORT_DICE:
                raise ActionError("bad effort_die")
            npc["effort_die"] = args["effort_die"]
        if "abilities" in args:
            npc["abilities"] = [st.sanitize_name(str(a), 60) for a in args["abilities"] if str(a).strip()][:6]

    elif action == "npc_delete":
        nid = str(_need(args, "npc_id"))
        state["npcs"] = [n for n in state["npcs"] if n["npc_id"] != nid]

    elif action == "npc_reveal":
        npc = _need_npc(state, args)
        npc["visible"] = bool(args.get("visible", True))
        st.add_log(
            state, actor, f"{npc['name']} {'takes the stage' if npc['visible'] else 'steps back into the shadows'}"
        )

    elif action == "npc_hearts":
        npc = _need_npc(state, args)
        npc["hearts"] = _shift_hearts(npc["hearts"], npc["hearts_max"], float(_need(args, "delta")))

    elif action == "loot_add":
        name = st.sanitize_name(str(_need(args, "name")), 60)
        if not name:
            raise ActionError("item needs a name")
        tier = str(args.get("tier", "common"))
        if tier not in TIERS:
            raise ActionError("tier must be one of " + ", ".join(TIERS))
        state["loot"].append(
            st.new_item(
                name,
                tier,
                st.sanitize_name(str(args.get("bonus", "")), 60),
                st.sanitize_name(str(args.get("description", "")), 200),
            )
        )

    elif action == "loot_update":
        item = _need_item(state, args)
        if "name" in args:
            item["name"] = st.sanitize_name(str(args["name"]), 60) or item["name"]
        if "tier" in args:
            if args["tier"] not in TIERS:
                raise ActionError("bad tier")
            item["tier"] = args["tier"]
        if "bonus" in args:
            item["bonus"] = st.sanitize_name(str(args["bonus"]), 60)
        if "description" in args:
            item["description"] = st.sanitize_name(str(args["description"]), 200)

    elif action == "loot_delete":
        iid = str(_need(args, "item_id"))
        state["loot"] = [i for i in state["loot"] if i["item_id"] != iid]

    elif action == "loot_assign":
        item = _need_item(state, args)
        pc_id = args.get("pc_id")
        if pc_id is None:
            if item["claimed_by"] is None:
                raise ActionError("item is already in the pool")
            item["claimed_by"] = None
        else:
            pc = st.find_party(state, str(pc_id))
            if pc is None:
                raise ActionError("no such pc")
            item["claimed_by"] = pc["pc_id"]
            st.add_log(state, actor, f"{item['name']} handed to {pc['name']}")

    elif action == "approve_join":
        token = str(_need(args, "device_token"))
        req = next((r for r in state["join_requests"] if r["device_token"] == token), None)
        if req is None:
            raise ActionError("no such join request")
        pc = _need_pc(state, args)
        _require_unbound(state, pc["pc_id"])
        st.drop_join_request(state, token)
        state["bindings"][token] = {"pc_id": pc["pc_id"]}
        st.add_log(state, actor, f"{req['name']} sat down as {pc['name']}")

    elif action == "reject_join":
        token = str(_need(args, "device_token"))
        req = next((r for r in state["join_requests"] if r["device_token"] == token), None)
        st.drop_join_request(state, token)
        if req:
            st.add_log(state, actor, f"turned {req['name']} away", audience="gm")

    elif action == "milestone_add":
        pc = _need_pc(state, args)
        reason = st.sanitize_name(str(_need(args, "reason")), 140)
        state["milestones"].append({"pc_id": pc["pc_id"], "pc_name": pc["name"], "reason": reason, "ts": st.now_iso()})
        st.add_log(state, actor, f"{pc['name']} earned a milestone — {reason}")

    elif action == "milestone_delete":
        idx = int(_need(args, "index"))
        if not (0 <= idx < len(state["milestones"])):
            raise ActionError("no such milestone")
        state["milestones"].pop(idx)

    elif action == "log_note":
        text = st.sanitize_name(str(_need(args, "text")), 200)
        audience = "all" if args.get("share", False) else "gm"
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
        pc["hearts"] = _shift_hearts(pc["hearts"], pc["hearts_max"], float(_need(args, "delta")))

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
