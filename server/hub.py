"""Room: the one live session plus every connected socket.

Server-authoritative; on every mutation the full (role-filtered) state is
broadcast. No deltas, no CRDT — state is a few KB.
"""

from __future__ import annotations

import asyncio
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
        # knocks are live-session state: a knock restored from a snapshot has
        # no connection behind it, so prune on boot — ghosts never linger
        if state["join_requests"]:
            state["join_requests"] = []
        # serializes broadcasts: two overlapping sends can never interleave
        # full-state frames across clients, and can never both try to reap
        # the same dead connection (the suspected watcher-killer, ticket 32)
        self._send_lock = asyncio.Lock()

    # -- mutation -----------------------------------------------------------

    def commit(self) -> None:
        """Version bump + snapshot after a successful mutation."""
        self.state["version"] = self.state.get("version", 0) + 1
        st.save_snapshot(self.state, self.data_dir)

    # -- fan-out --------------------------------------------------------------

    def _drop(self, conn: Connection) -> None:
        try:
            self.conns.remove(conn)
        except ValueError:
            pass  # an overlapping broadcast already reaped it

    def refresh_seats(self) -> None:
        """Re-derive every non-GM seat from state before sending.

        This is why approve_join/pc_delete need no socket bookkeeping: the
        binding write (or removal) takes effect on the next broadcast.
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
            "state": st.view_for(self.state, conn.role or "pending", conn.pc_id, conn.device_token),
        }
        await conn.ws.send_text(json.dumps(payload, ensure_ascii=False))

    async def broadcast(self) -> None:
        self.refresh_seats()
        async with self._send_lock:
            for conn in list(self.conns):
                try:
                    await self.send_to(conn)
                except Exception:
                    # dead socket: drop it; the client's reconnect loop will bring
                    # it back and get a fresh full state on hello
                    self._drop(conn)

    async def broadcast_to_gms(self) -> None:
        """GM-only notification (join knocks and their removal are GM business;
        a pending player's own view doesn't change when they knock)."""
        async with self._send_lock:
            for conn in list(self.conns):
                if conn.role != "gm":
                    continue
                try:
                    await self.send_to(conn)
                except Exception:
                    self._drop(conn)

    async def notify_rejection(self, device_token: str) -> None:
        """Send every pending conn for this token its rejected view, then close
        it with 4003 — under the send lock, so the refusal cannot be reordered
        against a concurrent broadcast (ticket 33)."""
        async with self._send_lock:
            for conn in list(self.conns):
                if conn.role == "pending" and conn.device_token == device_token:
                    try:
                        await self.send_to(conn)
                        await conn.ws.close(code=4003)
                    except Exception:
                        self._drop(conn)

    async def send_error(self, conn: Connection, message: str, code: str = "rejected") -> None:
        await conn.ws.send_text(json.dumps({"type": "error", "message": message, "code": code}))

    # -- join lifecycle -------------------------------------------------------

    def handle_hello_player(self, conn: Connection, device_token: str, name: str) -> bool:
        """Bind or re-bind a seat: a known device_token restores the same PC.
        With the server snapshot this is the whole 'lost phone' recovery — a new
        device just gets re-bound by the GM; hearts/inventory live server-side.
        Returns True when a NEW knock was created (the GM needs notifying);
        a rejected device or an already-known knock is silent."""
        conn.device_token = device_token
        conn.name = st.sanitize_name(name, 40) or "Player"
        binding = self.state["bindings"].get(device_token)
        if binding:
            conn.role = "player"
            conn.pc_id = binding["pc_id"]
            return False
        conn.role = "pending"
        # a rejected device stays rejected: no knock, no re-entry (ticket 33)
        if st.is_rejected(self.state, device_token):
            return False
        if not any(r["device_token"] == device_token for r in self.state["join_requests"]):
            self.state["join_requests"].append({"device_token": device_token, "name": conn.name})
            self.commit()
            return True
        return False
