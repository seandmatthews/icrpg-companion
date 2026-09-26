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


def load_pack(state: dict, pack: str) -> str:
    path = _pack_path(pack)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise actions.ActionError(f"no starter pack named '{pack}'")
    except json.JSONDecodeError:
        raise actions.ActionError(f"starter pack '{pack}' is corrupt")

    added: list[str] = []

    if "targets" in data and state["loot"] == [] and state["party"] == []:
        state["targets"] = data["targets"]

    existing_names = {i["name"].lower() for i in state["loot"]}
    existing_labels = {t["label"].lower() for t in state["timers"]}

    for item in data.get("loot", []):
        if item["name"].lower() in existing_names:
            continue
        state["loot"].append(
            st.new_item(item["name"], item.get("tier", "common"),
                        item.get("bonus", ""), item.get("description", ""))
        )
        added.append(item["name"])

    for t in data.get("timers", []):
        if t["label"].lower() in existing_labels:
            continue
        if t["kind"] == "alarm":
            state["timers"].append(st.new_timer(t["label"], "alarm", t["duration_s"], None))
        else:
            state["timers"].append(st.new_timer(t["label"], "rounds", None, t["rounds"]))
        added.append(t["label"])

    return ", ".join(added) if added else "nothing new (already loaded)"
