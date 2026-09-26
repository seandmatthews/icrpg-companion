"""Room: the one live session plus every connected socket.

Server-authoritative; on every mutation the full (role-filtered) state is
broadcast. No deltas, no CRDT — state is a few KB.
"""

from __future__ import annotations

import json

from . import state as st


class Connection:
    def __init__(self) -> None:
        self.ws = None  # set on accept
        self.role: str | None = None  # None until hello | gm | player | pending
        self.pc_id: str | None = None
        self.device_token: str | None = None
        self.name: str = ""


class Room:
    def __init__(self, state: dict, data_dir: str) -> None:
        self.state = state
        self.data_dir = data_dir
        self.conns: list[Connection] = []

    # -- mutation -----------------------------------------------------------

    def commit(self) -> None:
        """Version bump + snapshot after a successful mutation."""
        self.state["version"] = self.state.get("version", 0) + 1
        st.save_snapshot(self.state, self.data_dir)

    # -- fan-out --------------------------------------------------------------

    def refresh_seats(self) -> None:
        """Re-derive every non-GM connection's seat from state before sending.

        This is what makes approval/disconnect flows work without bookkeeping
        in the action handlers: approve_join writes a binding, and the next
        broadcast flips the pending socket to seated; pc_delete or
        session_reset silently unseats the affected sockets again.
        """
        for conn in self.conns:
            if conn.role == "gm":
                continue
            binding = self.state["bindings"].get(conn.device_token or "")
            if binding:
                conn.role, conn.pc_id = "player", binding["pc_id"]
            elif conn.device_token:
                conn.role, conn.pc_id = "pending", None

    async def send_to(self, conn: Connection) -> None:
        self.refresh_seats()
        payload = {
            "type": "state",
            "server_time": st.now(),
            "state": st.view_for(self.state, conn.role or "pending", conn.pc_id),
        }
        await conn.ws.send_text(json.dumps(payload, ensure_ascii=False))

    async def broadcast(self) -> None:
        self.refresh_seats()
        for conn in list(self.conns):
            try:
                await self.send_to(conn)
            except Exception:
                # dead socket: drop it; the client's reconnect loop will bring
                # it back and get a fresh full state on hello
                self.conns.remove(conn)

    async def broadcast_to_gms(self) -> None:
        """GM-only notification (join knocks and their removal are GM business;
        a pending player's own view doesn't change when they knock)."""
        for conn in list(self.conns):
            if conn.role != "gm":
                continue
            try:
                await self.send_to(conn)
            except Exception:
                self.conns.remove(conn)

    async def send_error(self, conn: Connection, message: str, code: str = "rejected") -> None:
        await conn.ws.send_text(json.dumps({"type": "error", "message": message, "code": code}))

    # -- join lifecycle -------------------------------------------------------

    def drop_join_request(self, device_token: str) -> bool:
        before = len(self.state["join_requests"])
        self.state["join_requests"] = [
            r for r in self.state["join_requests"] if r["device_token"] != device_token
        ]
        return len(self.state["join_requests"]) < before

    def handle_hello_player(self, conn: Connection, device_token: str, name: str) -> None:
        """Bind or re-bind a player seat. Reconnects with a known device token
        restore the same seat — that, plus the server snapshot, is the whole
        'lost phone' recovery story (new device = GM re-binds the same PC,
        whose hearts/inventory live server-side)."""
        conn.device_token = device_token
        conn.name = st.sanitize_name(name, 40) or "Player"
        binding = self.state["bindings"].get(device_token)
        if binding:
            conn.role = "player"
            conn.pc_id = binding["pc_id"]
        else:
            conn.role = "pending"
            if not any(r["device_token"] == device_token for r in self.state["join_requests"]):
                self.state["join_requests"].append({"device_token": device_token, "name": conn.name})
                self.commit()
