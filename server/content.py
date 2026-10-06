"""Starter content packs: optional seeds a GM can load into an empty session.

All pack content is original flavor written for this project — no rulebook
text is reproduced. Packs only fill gaps (loot names that aren't already in
the pool, timers that don't exist yet); they never clobber GM edits.
"""

from __future__ import annotations

import json
import os

from . import actions, state as st

PACKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content")


def _pack_path(pack: str) -> str:
    # pack names are file-system hostile by construction: alnum + dash only
    if not pack or not all(c.isalnum() or c == "-" for c in pack):
        raise actions.ActionError("bad pack name")
    return os.path.join(PACKS_DIR, f"{pack}.json")


def _validate_pack(data, pack: str) -> tuple[list, list, dict | None]:
    """Validate every entry before anything is applied — a malformed pack
    must fail loudly with a readable ActionError and nothing half-appended
    (ticket 32). Returns (loot, timers, targets) with cleaned values."""
    if not isinstance(data, dict):
        raise actions.ActionError(f"starter pack '{pack}' must be a JSON object")

    targets = data.get("targets")
    if targets is not None:
        ok = isinstance(targets, dict) and all(
            isinstance(targets.get(k), int) and not isinstance(targets.get(k), bool)
            for k in ("default", "scene")
        )
        if not ok:
            raise actions.ActionError(
                f"starter pack '{pack}': targets must be an object with integer default/scene"
            )

    loot_raw = data.get("loot", [])
    if not isinstance(loot_raw, list):
        raise actions.ActionError(f"starter pack '{pack}': 'loot' must be a list")
    loot = []
    for i, item in enumerate(loot_raw):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise actions.ActionError(f"starter pack '{pack}' loot entry {i}: needs a name")
        tier = item.get("tier", "common")
        if tier not in actions.TIERS:
            raise actions.ActionError(
                f"starter pack '{pack}' loot entry {i}: tier must be one of " + ", ".join(actions.TIERS)
            )
        bonus, description = item.get("bonus", ""), item.get("description", "")
        if not isinstance(bonus, str) or not isinstance(description, str):
            raise actions.ActionError(f"starter pack '{pack}' loot entry {i}: bonus/description must be strings")
        loot.append((item["name"], tier, bonus, description))

    timers_raw = data.get("timers", [])
    if not isinstance(timers_raw, list):
        raise actions.ActionError(f"starter pack '{pack}': 'timers' must be a list")
    timers = []
    for i, t in enumerate(timers_raw):
        if not isinstance(t, dict) or not isinstance(t.get("label"), str) or not t["label"].strip():
            raise actions.ActionError(f"starter pack '{pack}' timers entry {i}: needs a label")
        kind = t.get("kind")
        if kind == "alarm":
            d = t.get("duration_s")
            if isinstance(d, bool) or not isinstance(d, int) or not (1 <= d <= 24 * 3600):
                raise actions.ActionError(
                    f"starter pack '{pack}' timers entry {i}: alarm needs duration_s (1..86400)"
                )
            timers.append((t["label"], "alarm", d, None))
        elif kind == "rounds":
            r = t.get("rounds")
            if isinstance(r, bool) or not isinstance(r, int) or not (1 <= r <= 99):
                raise actions.ActionError(
                    f"starter pack '{pack}' timers entry {i}: rounds timer needs rounds (1..99)"
                )
            timers.append((t["label"], "rounds", None, r))
        else:
            raise actions.ActionError(f"starter pack '{pack}' timers entry {i}: kind must be alarm or rounds")

    return loot, timers, targets


def load_pack(state: dict, pack: str) -> str:
    path = _pack_path(pack)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise actions.ActionError(f"no starter pack named '{pack}'")
    except json.JSONDecodeError:
        raise actions.ActionError(f"starter pack '{pack}' is corrupt")

    loot, timers, targets = _validate_pack(data, pack)

    added: list[str] = []

    if targets is not None and state["loot"] == [] and state["party"] == []:
        state["targets"] = targets

    existing_names = {i["name"].lower() for i in state["loot"]}
    existing_labels = {t["label"].lower() for t in state["timers"]}

    for name, tier, bonus, description in loot:
        if name.lower() in existing_names:
            continue
        state["loot"].append(
            st.new_item(name, tier, st.sanitize_name(bonus, 60), st.sanitize_name(description, 200))
        )
        added.append(name)

    for label, kind, duration_s, rounds in timers:
        if label.lower() in existing_labels:
            continue
        state["timers"].append(st.new_timer(label, kind, duration_s, rounds))
        added.append(label)

    return ", ".join(added) if added else "nothing new (already loaded)"
