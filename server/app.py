"""FastAPI application: WS hub, bootstrap endpoint, static client hosting."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import socket
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import actions, state as st
from .hub import Connection, Room

_log = logging.getLogger("table-companion")

HELLO_DEADLINE = 10.0  # a socket that never says hello is closed (ticket 38)

NOT_BUILT_PAGE = (
    "<!doctype html><meta charset='utf-8'><title>table companion</title>"
    "<body style='font-family:system-ui;background:#16161a;color:#f5f0e6;"
    "display:grid;place-items:center;height:100vh;margin:0'>"
    "<div style='text-align:center'><h1>Client not built</h1>"
    "<p>The web client hasn't been compiled yet.</p>"
    "<p><code>cd client &&amp; npm install &amp;&amp; npm run build</code></p>"
    "<p>Then restart this server.</p></div></body>"
)

CLIENT_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "client", "dist")


def detect_lan_candidates() -> list[str]:
    """Best-effort LAN IPs for the QR code, best first: UDP connect() picks a
    route without sending packets. Rank: home-LAN 192.168 beats 10.x beats
    172.16-31 (real networks live there too, but so do WSL/Hyper-V/Docker
    adapters) beats anything else (ticket 47)."""
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

    return _rank_candidates(candidates)


def _rank_candidates(candidates: list[str]) -> list[str]:
    """Pure ranking so tests can inject candidate sets (ticket 47)."""

    def rank(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172.") and ip.split(".")[1].isdigit() and 16 <= int(ip.split(".")[1]) <= 31:
            return 2
        return 3

    return sorted(candidates, key=rank)


def detect_lan_ip() -> str | None:
    candidates = detect_lan_candidates()
    return candidates[0] if candidates else None


def create_app(data_dir: str, fresh: bool = False, lan_ip: str | None = None) -> FastAPI:
    st.acquire_lock(data_dir)
    import atexit

    atexit.register(st.release_lock, data_dir)
    # --fresh no longer deletes at boot (ticket 46): a bind failure or Ctrl+C
    # before the first action must leave the previous session on disk. The
    # clear happens at the first commit instead.
    state, load_reason = st.load_snapshot(data_dir) if not fresh else (None, None)
    if state is None:
        state = st.new_state(st.gen_room_code(), secrets.token_urlsafe(12))
    room = Room(state, data_dir, pending_clear=fresh)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_timer_watcher(room))
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task  # no "Task was destroyed but it is pending" noise

    self_lan_ip = lan_ip  # computed once at boot by run.py (ticket 47)

    app = FastAPI(lifespan=lifespan, title="table-companion")
    app.state_model = state  # for run.py banner + tests
    app.state_room = room  # for tests (dead-conn / broadcast-race pinning)
    app.load_reason = load_reason  # snapshot fallback disclosure for the banner

    @app.get("/api/bootstrap")
    async def bootstrap() -> JSONResponse:
        return JSONResponse(
            {
                "room_code": room.state["room_code"],
                "session_id": room.state["session_id"],
                "title": room.state["title"],
                "version": room.state["version"],
                "server_time": st.now(),
                "lan_ip": self_lan_ip,
            }
        )

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # browsers always send Origin on a WebSocket handshake; a cross-site
        # origin is a drive-by webpage, not this client — refuse the handshake
        origin = ws.headers.get("origin")
        if origin and (
            origin == "null" or urlparse(origin).netloc not in ("", ws.headers.get("host"))
        ):
            await ws.close()
            return
        await ws.accept()
        conn = Connection()
        conn.ws = ws
        conn.opened = st.now()
        room.conns.append(conn)
        try:
            while True:
                try:
                    try:
                        msg = json.loads(await ws.receive_text())
                    except json.JSONDecodeError:
                        await room.send_error(conn, "garbled message")
                        continue
                    if not isinstance(msg, dict):
                        # a non-object frame must be an error, never a crash
                        # ("x" / [1] / null used to abort the socket, ticket 32)
                        await room.send_error(conn, "garbled message")
                        continue
                    mtype = msg.get("type")

                    if mtype == "ping":
                        await ws.send_text(json.dumps({"type": "pong", "server_time": st.now()}))

                    elif mtype == "hello_gm":
                        if not secrets.compare_digest(
                            str(msg.get("gm_token") or "").encode("utf-8"),
                            room.state["gm_token"].encode("utf-8"),
                        ):
                            await room.send_error(conn, "wrong GM key", code="auth")
                            await ws.close(code=4001)
                            return
                        conn.role = "gm"
                        conn.device_token = str(msg.get("device_token") or "")
                        await room.send_to(conn)

                    elif mtype == "hello_player":
                        if msg.get("room") != room.state["room_code"]:
                            await room.send_error(conn, "wrong room code", code="auth")
                            await ws.close(code=4002)
                            return
                        device_token = str(msg.get("device_token") or "")
                        if not (1 <= len(device_token) <= 64):
                            # no more server-minted ghost identities: a client
                            # without a token is broken, not anonymous (ticket 38)
                            await room.send_error(conn, "a valid device token is required")
                            await ws.close(code=4002)
                            return
                        knock_created = room.handle_hello_player(
                            conn, device_token, str(msg.get("name") or "Player")
                        )
                        await room.send_to(conn)
                        if knock_created:
                            await room.broadcast_to_gms()  # GM learns about the knock

                    elif mtype == "action":
                        if conn.role not in ("gm", "player"):
                            await room.send_error(conn, "say hello first")
                            continue
                        args = msg.get("args")
                        if args is None:
                            args = {}
                        if not isinstance(args, dict):
                            await room.send_error(conn, "args must be an object")
                            continue
                        actor = "GM" if conn.role == "gm" else (conn.name or "Player")
                        try:
                            actions.apply_action(
                                room.state,
                                conn.role,
                                actor,
                                str(msg.get("action", "")),
                                args,
                                pc_id=conn.pc_id,
                            )
                            st.check_timers(room.state, st.now())
                            room.commit()
                        except actions.ActionError as e:
                            await room.send_error(conn, str(e))
                            continue
                        # a rejected knock tells the player it's over, then closes
                        # their socket — the pending view now carries rejected: true
                        if msg.get("action") == "reject_join":
                            await room.notify_rejection(str(args.get("device_token") or ""))
                        await room.broadcast()

                    else:
                        await room.send_error(conn, f"unknown message type '{mtype}'")
                except WebSocketDisconnect:
                    raise
                except Exception:
                    # a failing send (or close) on a socket that just died must
                    # not escape as an unhandled per-connection error (ticket 38);
                    # the finally below still runs, so cleanup is unaffected
                    _log.warning("ws handler error; closing connection", exc_info=True)
                    return

        except WebSocketDisconnect:
            pass
        finally:
            room._drop(conn)  # one guarded removal path everywhere (ticket 32)
            # a pending player who left is a ghost knock — clear it for the GM,
            # but only when no other live tab of the same device holds it
            # (two tabs share one token and one knock — ticket 37)
            if (
                conn.role == "pending"
                and conn.device_token
                and not any(
                    other.role != "gm" and other.device_token == conn.device_token
                    for other in room.conns
                )
                and st.drop_join_request(room.state, conn.device_token)
            ):
                room.commit()
                await room.broadcast_to_gms()

    async def _timer_watcher(room: Room) -> None:
        """Server-side alarm authority: expiry is resolved here, once.
        A failed tick is logged, never fatal: a failed broadcast still leaves
        the (idempotent) resolution in memory, delivered by the next action's
        broadcast — but the watcher itself must not die (ticket 32). Also
        sweeps sockets that never said hello (ticket 38)."""
        while True:
            await asyncio.sleep(1)
            try:
                if st.check_timers(room.state, st.now()):
                    room.commit()
                    await room.broadcast()
            except Exception:
                _log.warning("timer watcher tick failed; will retry", exc_info=True)
            # hello-deadline sweep runs AFTER timer authority: a failing close
            # must never delay an alarm (ticket 38)
            try:
                for conn in list(room.conns):
                    if conn.role is None and st.now() - conn.opened > HELLO_DEADLINE:
                        await conn.ws.close(code=4000)
            except Exception:
                _log.warning("hello-deadline sweep failed", exc_info=True)

    index_html = os.path.join(CLIENT_DIST, "index.html")
    if not os.path.exists(index_html):
        _log.warning("client build missing (%s) — / will serve a build hint", index_html)

    @app.get("/join", include_in_schema=False)
    async def join_page():
        if not os.path.exists(index_html):
            return HTMLResponse(NOT_BUILT_PAGE)
        return FileResponse(index_html)

    if os.path.isdir(CLIENT_DIST):
        app.mount("/", StaticFiles(directory=CLIENT_DIST, html=True), name="client")
    else:

        @app.get("/", include_in_schema=False)
        async def root_fallback():
            return HTMLResponse(NOT_BUILT_PAGE)

    return app
