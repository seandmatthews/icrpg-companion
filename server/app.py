"""FastAPI application: WS hub, bootstrap endpoint, static client hosting."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import actions, state as st
from .hub import Connection, Room

CLIENT_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client", "dist")


def detect_lan_ip() -> str | None:
    """Best-effort LAN IP for the QR code: UDP connect() picks a route without
    sending packets; home-LAN ranges beat VPN/Tailscale adapters. Falls back
    to the hostname, then None."""
    candidates: list[str] = []
    for target in (("8.8.8.8", 80), ("192.168.0.1", 80)):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(target)
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."):
                    candidates.append(ip)
            finally:
                s.close()
        except OSError:
            continue
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            candidates.append(ip)
    except OSError:
        pass
    for rank in ("192.168.", "10."):
        for ip in candidates:
            if ip.startswith(rank):
                return ip
    return candidates[0] if candidates else None


def create_app(data_dir: str, fresh: bool = False) -> FastAPI:
    if fresh:
        st.clear_snapshot(data_dir)
    state = st.load_snapshot(data_dir)
    if state is None:
        state = st.new_state(st.gen_room_code(), secrets.token_urlsafe(12))
    room = Room(state, data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_timer_watcher(room))
        yield
        task.cancel()

    app = FastAPI(lifespan=lifespan, title="table-companion")
    app.state_model = state  # for run.py banner + tests

    @app.get("/api/bootstrap")
    async def bootstrap() -> JSONResponse:
        return JSONResponse(
            {
                "room_code": room.state["room_code"],
                "session_id": room.state["session_id"],
                "title": room.state["title"],
                "version": room.state["version"],
                "server_time": st.now(),
                "lan_ip": detect_lan_ip(),
            }
        )

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        conn = Connection()
        conn.ws = ws
        room.conns.append(conn)
        try:
            while True:
                try:
                    msg = json.loads(await ws.receive_text())
                except json.JSONDecodeError:
                    await room.send_error(conn, "garbled message")
                    continue
                mtype = msg.get("type")

                if mtype == "ping":
                    await ws.send_text(json.dumps({"type": "pong", "server_time": st.now()}))

                elif mtype == "hello_gm":
                    if msg.get("gm_token") != room.state["gm_token"]:
                        await room.send_error(conn, "wrong GM key", code="auth")
                        await ws.close(code=4001)
                        return
                    conn.role = "gm"
                    conn.device_token = msg.get("device_token")
                    await room.send_to(conn)

                elif mtype == "hello_player":
                    if msg.get("room") != room.state["room_code"]:
                        await room.send_error(conn, "wrong room code", code="auth")
                        await ws.close(code=4002)
                        return
                    room.handle_hello_player(
                        conn, str(msg.get("device_token") or st.id4("dev")), str(msg.get("name") or "Player")
                    )
                    await room.send_to(conn)
                    if conn.role == "pending":
                        await room.broadcast_to_gms()  # GM learns about the knock

                elif mtype == "action":
                    if conn.role not in ("gm", "player"):
                        await room.send_error(conn, "say hello first")
                        continue
                    actor = "GM" if conn.role == "gm" else (conn.name or "Player")
                    try:
                        actions.apply_action(
                            room.state,
                            conn.role,
                            actor,
                            str(msg.get("action", "")),
                            msg.get("args") or {},
                            pc_id=conn.pc_id,
                        )
                        st.check_timers(room.state, st.now())
                        room.commit()
                    except actions.ActionError as e:
                        await room.send_error(conn, str(e))
                        continue
                    await room.broadcast()

                else:
                    await room.send_error(conn, f"unknown message type '{mtype}'")

        except WebSocketDisconnect:
            pass
        finally:
            if conn in room.conns:
                room.conns.remove(conn)
            # a pending player who left is a ghost knock — clear it for the GM
            if conn.role == "pending" and conn.device_token and st.drop_join_request(room.state, conn.device_token):
                room.commit()
                await room.broadcast_to_gms()

    async def _timer_watcher(room: Room) -> None:
        """Server-side alarm authority: expiry is resolved here, once."""
        while True:
            await asyncio.sleep(1)
            if st.check_timers(room.state, st.now()):
                room.commit()
                await room.broadcast()

    index_html = os.path.join(CLIENT_DIST, "index.html")

    @app.get("/join", include_in_schema=False)
    async def join_page() -> FileResponse:
        return FileResponse(index_html)

    if os.path.isdir(CLIENT_DIST):
        app.mount("/", StaticFiles(directory=CLIENT_DIST, html=True), name="client")

    return app
