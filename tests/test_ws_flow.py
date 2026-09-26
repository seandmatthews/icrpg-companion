"""End-to-end WebSocket flow tests against a real uvicorn server.

(The starlette TestClient's WebSocketTestSession is broken with this
starlette/anyio combination — and the shared site-packages must not be
upgraded under the studio — so WS tests boot a live loopback server and
speak real WebSocket with the `websockets` sync client.)
"""

import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
from websockets.sync.client import connect as ws_connect

from server import actions
from server.app import create_app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def boot(data_dir: str, fresh: bool = True):
    app = create_app(data_dir, fresh=fresh)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=_free_port(), log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("test server failed to start")
    port = server.servers[0].sockets[0].getsockname()[1]
    return app, server, thread, f"ws://127.0.0.1:{port}"


def shutdown(server, thread) -> None:
    server.should_exit = True
    thread.join(timeout=5)


class WS:
    """Tiny JSON wrapper over the sync websockets client."""

    def __init__(self, url):
        self.ws = ws_connect(url)

    def send(self, **msg):
        self.ws.send(json.dumps(msg))

    def recv(self, timeout=5):
        return json.loads(self.ws.recv(timeout))

    def close(self):
        self.ws.close()


@pytest.fixture()
def ns(tmp_path):
    app, server, thread, ws_base = boot(str(tmp_path))
    yield SimpleNamespace(
        app=app, state=app.state_model, ws_base=ws_base, data_dir=str(tmp_path)
    )
    shutdown(server, thread)


def gm_session(ns) -> WS:
    ws = WS(ns.ws_base + "/ws")
    ws.send(type="hello_gm", gm_token=ns.state["gm_token"])
    hello = ws.recv()
    assert hello["type"] == "state"
    return ws


def player_session(ns, dev, name="Sam") -> WS:
    ws = WS(ns.ws_base + "/ws")
    ws.send(type="hello_player", room=ns.state["room_code"], device_token=dev, name=name)
    return ws


def do(ws: WS, action: str, **args) -> dict:
    """Send a GM action and block until its broadcast comes back — keeps the
    tests deterministic against the async server."""
    ws.send(type="action", action=action, args=args)
    msg = ws.recv()
    assert msg["type"] == "state", msg
    return msg["state"]


def test_bootstrap_exposes_room_but_not_secret(ns):
    import urllib.request

    http_base = ns.ws_base.replace("ws://", "http://")
    with urllib.request.urlopen(http_base + "/api/bootstrap", timeout=5) as r:
        body = json.loads(r.read())
    assert body["room_code"] == ns.state["room_code"]
    assert "gm_token" not in body


def test_gm_auth_wrong_key_rejected(ns):
    ws = WS(ns.ws_base + "/ws")
    ws.send(type="hello_gm", gm_token="nope")
    err = ws.recv()
    assert err["code"] == "auth"


def test_player_join_approval_claim_flow(ns):
    state, gm = ns.state, gm_session(ns)
    do(gm, "pc_add", name="Vex", player_label="Sam")
    do(gm, "loot_add", name="Ford signet ring")
    pc_id, item_id = state["party"][0]["pc_id"], state["loot"][0]["item_id"]

    pws = player_session(ns, "device-abc")
    assert pws.recv()["state"]["status"] == "pending"

    gm_view = gm.recv()["state"]  # the knock broadcast
    assert any(r["device_token"] == "device-abc" for r in gm_view["join_requests"])

    gm.send(type="action", action="approve_join", args={"device_token": "device-abc", "pc_id": pc_id})
    seated = pws.recv()["state"]
    assert seated["you"]["pc_id"] == pc_id
    assert "join_requests" not in seated and "bindings" not in seated
    gm.recv()  # approval broadcast

    pws.send(type="action", action="player_claim", args={"item_id": item_id})
    claimed = pws.recv()["state"]
    assert claimed["loot"][0]["claimed_by"] == pc_id
    assert gm.recv()["state"]["loot"][0]["claimed_by"] == pc_id

    pws.send(type="action", action="pc_add", args={"name": "Sneaky"})
    assert pws.recv()["type"] == "error"
    assert len(state["party"]) == 1

    pws.close()
    gm.close()


def test_rejoin_restores_seat_without_new_request(ns):
    state = ns.state
    gm = gm_session(ns)
    do(gm, "pc_add", name="Vex")
    pc_id = state["party"][0]["pc_id"]

    pws = player_session(ns, "device-abc")
    pws.recv()  # pending
    gm.recv()  # knock
    gm.send(type="action", action="approve_join", args={"device_token": "device-abc", "pc_id": pc_id})
    assert pws.recv()["state"]["you"]["pc_id"] == pc_id
    gm.recv()
    pws.close()

    pws2 = player_session(ns, "device-abc")
    assert pws2.recv()["state"]["you"]["pc_id"] == pc_id
    pws2.close()
    gm.close()


def test_pending_disconnect_clears_the_knock(ns):
    gm = gm_session(ns)
    pws = player_session(ns, "ghost", name="Ghost")
    pws.recv()
    gm.recv()
    pws.close()
    gm_view = gm.recv()["state"]
    assert not any(r["device_token"] == "ghost" for r in gm_view["join_requests"])
    gm.close()


def test_wrong_room_code_rejected(ns):
    ws = WS(ns.ws_base + "/ws")
    ws.send(type="hello_player", room="NOPE", device_token="d", name="Sam")
    assert ws.recv()["code"] == "auth"


def test_action_from_silent_socket_rejected(ns):
    ws = WS(ns.ws_base + "/ws")
    ws.send(type="action", action="alarm_dismiss")
    assert ws.recv()["type"] == "error"


def test_player_view_hides_hidden_npcs_and_gm_log(ns):
    state = ns.state
    gm = gm_session(ns)
    do(gm, "pc_add", name="Vex")
    do(gm, "npc_add", name="Secret Boss", visible=False)
    do(gm, "npc_add", name="Town Guard", visible=True)
    do(gm, "log_note", text="ambush plan: they never suspect the mule")
    pc_id = state["party"][0]["pc_id"]

    pws = player_session(ns, "dev-hide")
    pws.recv()
    gm.recv()
    gm.send(type="action", action="approve_join", args={"device_token": "dev-hide", "pc_id": pc_id})
    view = pws.recv()["state"]
    names = [n["name"] for n in view["npcs"]]
    assert "Secret Boss" not in names and "Town Guard" in names
    assert all(e["audience"] == "all" for e in view["log"])
    assert not any("ambush plan" in e["text"] for e in view["log"])
    pws.close()
    gm.close()


def test_ping_pong_clock_sync(ns):
    ws = WS(ns.ws_base + "/ws")
    ws.send(type="ping")
    pong = ws.recv()
    assert pong["type"] == "pong" and abs(pong["server_time"] - time.time()) < 30
    ws.close()


def test_snapshot_survives_restart(tmp_path):
    data_dir = str(tmp_path)
    app, server, thread, ws_base = boot(data_dir, fresh=True)
    state = app.state_model
    actions.apply_action(state, "gm", "GM", "pc_add", {"name": "Vex"})
    actions.apply_action(state, "gm", "GM", "pc_hearts", {"pc_id": state["party"][0]["pc_id"], "delta": -1})
    # a Room commit saves; here we drove the state directly, so save explicitly
    from server import state as st

    st.save_snapshot(state, data_dir)
    room_code, gm_token, version = state["room_code"], state["gm_token"], state["version"]
    shutdown(server, thread)

    app2, server2, thread2, _ = boot(data_dir, fresh=False)
    state2 = app2.state_model
    assert state2["room_code"] == room_code
    assert state2["gm_token"] == gm_token  # GM's browser session survives too
    assert state2["version"] == version
    assert state2["party"][0]["name"] == "Vex"
    assert state2["party"][0]["hearts"] == state2["party"][0]["hearts_max"] - 1
    shutdown(server2, thread2)

    app3, server3, thread3, _ = boot(data_dir, fresh=True)
    assert app3.state_model["party"] == []
    shutdown(server3, thread3)
