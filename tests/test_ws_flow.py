"""End-to-end WebSocket flow tests against a live uvicorn loopback server.

WebSocketTestSession is broken with this starlette/anyio combo (and the
shared site-packages must not be upgraded), so these use the real
`websockets` sync client.

Harness (ticket 52): TestServer is a context manager whose close() RAISES
if the server thread did not die, every booted server registers in
TestServer.LIVE, and a session finalizer asserts nothing survived — a test
that fails mid-flight must not leak a live uvicorn holding a snapshot file.
WS closes its socket on exit, so an assertion failure cannot strand a
client on the server either.
"""

import json
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
from websockets.sync.client import connect as ws_connect

from server import actions
from server.app import create_app


class TestServer:
    __test__ = False  # it is a fixture-style harness, not a pytest collection

    LIVE: list["TestServer"] = []

    def __init__(self, data_dir: str, fresh: bool = True):
        self.app = create_app(data_dir, fresh=fresh)
        # port=0: bind an ephemeral port and read the real one off the socket —
        # a pre-bound probe socket had a TOCTOU window
        config = uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        TestServer.LIVE.append(self)
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.02)
        if not self.server.started:
            self.close()  # stop the late-binding thread before raising
            raise RuntimeError("test server failed to start")
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.ws_base = f"ws://127.0.0.1:{port}"

    def close(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("test server thread did not die within 5s — open sockets?")
        if self in TestServer.LIVE:
            TestServer.LIVE.remove(self)

    def __enter__(self) -> "TestServer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def test_close_raises_when_the_server_thread_stalls():
    """Pin the loud-shutdown contract without booting uvicorn: a thread that
    ignores should_exit must make close() raise (not pass silently), and the
    abandoned server must stay in LIVE for the session finalizer to catch."""
    srv = object.__new__(TestServer)
    srv.server = SimpleNamespace(should_exit=False)
    gate = threading.Event()
    srv.thread = threading.Thread(target=gate.wait, daemon=True)
    TestServer.LIVE.append(srv)
    srv.thread.start()
    try:
        with pytest.raises(RuntimeError, match="did not die"):
            srv.close()
        assert srv in TestServer.LIVE  # the finalizer will flag this leak
    finally:
        gate.set()
        srv.thread.join(timeout=5)
        if srv in TestServer.LIVE:
            TestServer.LIVE.remove(srv)


@pytest.fixture(scope="session", autouse=True)
def _no_leaked_servers():
    """Harness pin: at session end, every server any test booted must be
    shut down — including ones abandoned by a failed test (they are removed
    from LIVE only by close(), so anything left here was never closed)."""
    yield
    abandoned = [s for s in TestServer.LIVE if s.thread.is_alive()]
    assert not abandoned, f"tests leaked live server threads: {abandoned}"


class WS:
    """Tiny JSON wrapper over the sync websockets client; context-managed."""

    def __init__(self, url):
        self.ws = ws_connect(url)

    def send(self, **msg):
        self.ws.send(json.dumps(msg))

    def recv(self, timeout=5):
        return json.loads(self.ws.recv(timeout))

    def close(self):
        self.ws.close()

    def __enter__(self) -> "WS":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@pytest.fixture()
def ns(tmp_path):
    with TestServer(str(tmp_path)) as srv:
        yield SimpleNamespace(
            app=srv.app, state=srv.app.state_model, ws_base=srv.ws_base, data_dir=str(tmp_path)
        )


def gm_session(ns) -> WS:
    ws = WS(ns.ws_base + "/ws")
    ws.send(type="hello_gm", gm_token=ns.state["gm_token"])
    hello = ws.recv()
    assert hello["type"] == "state"
    # the GM key must never ride any state frame, GM's own included
    assert "gm_token" not in hello["state"]
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


def _assert_closed_with(ws: WS, code: int) -> None:
    """The auth error frame must be followed by the server actually closing
    the socket with the agreed code — a regression that leaves the
    connection open is a bug, not a nit."""
    with pytest.raises(Exception) as ei:
        ws.recv()
    assert getattr(ei.value, "rcvd", None) is not None
    assert ei.value.rcvd.code == code


def test_gm_auth_wrong_key_rejected(ns):
    with WS(ns.ws_base + "/ws") as ws:
        ws.send(type="hello_gm", gm_token="nope")
        err = ws.recv()
        assert err["code"] == "auth"
        _assert_closed_with(ws, 4001)


def test_player_join_approval_claim_flow(ns):
    state = ns.state
    with gm_session(ns) as gm:
        do(gm, "pc_add", name="Vex", player_label="Sam")
        do(gm, "loot_add", name="Ford signet ring")
        pc_id, item_id = state["party"][0]["pc_id"], state["loot"][0]["item_id"]

        with player_session(ns, "device-abc") as pws:
            assert pws.recv()["state"]["status"] == "pending"

            gm_view = gm.recv()["state"]  # the knock broadcast
            assert any(r["device_token"] == "device-abc" for r in gm_view["join_requests"])

            gm.send(type="action", action="approve_join", args={"device_token": "device-abc", "pc_id": pc_id})
            seated = pws.recv()["state"]
            assert seated["you"]["pc_id"] == pc_id
            assert "join_requests" not in seated and "bindings" not in seated
            assert "gm_token" not in seated
            gm.recv()  # approval broadcast

            pws.send(type="action", action="player_claim", args={"item_id": item_id})
            claimed = pws.recv()["state"]
            assert claimed["loot"][0]["claimed_by"] == pc_id
            assert gm.recv()["state"]["loot"][0]["claimed_by"] == pc_id

            pws.send(type="action", action="pc_add", args={"name": "Sneaky"})
            assert pws.recv()["type"] == "error"
            assert len(state["party"]) == 1


def test_rejoin_restores_seat_without_new_request(ns):
    state = ns.state
    with gm_session(ns) as gm:
        do(gm, "pc_add", name="Vex")
        pc_id = state["party"][0]["pc_id"]

        with player_session(ns, "device-abc") as pws:
            pws.recv()  # pending
            gm.recv()  # knock
            gm.send(type="action", action="approve_join", args={"device_token": "device-abc", "pc_id": pc_id})
            assert pws.recv()["state"]["you"]["pc_id"] == pc_id
            gm.recv()

        with player_session(ns, "device-abc") as pws2:
            assert pws2.recv()["state"]["you"]["pc_id"] == pc_id
            # the name of this test is a contract: the re-hello must NOT
            # re-knock — read the GM's fresh view and prove the knock panel
            # is still empty for this device
            gm_view = do(gm, "log_note", text="probe")
            assert not any(r["device_token"] == "device-abc" for r in gm_view["join_requests"])


def test_pending_disconnect_clears_the_knock(ns):
    with gm_session(ns) as gm:
        with player_session(ns, "ghost", name="Ghost") as pws:
            pws.recv()
            gm.recv()
        gm_view = gm.recv()["state"]
        assert not any(r["device_token"] == "ghost" for r in gm_view["join_requests"])


def test_wrong_room_code_rejected(ns):
    with WS(ns.ws_base + "/ws") as ws:
        ws.send(type="hello_player", room="NOPE", device_token="d", name="Sam")
        assert ws.recv()["code"] == "auth"
        _assert_closed_with(ws, 4002)


def test_action_from_silent_socket_rejected(ns):
    with WS(ns.ws_base + "/ws") as ws:
        ws.send(type="action", action="alarm_dismiss")
        assert ws.recv()["type"] == "error"


def test_player_view_hides_hidden_npcs_and_gm_log(ns):
    state = ns.state
    with gm_session(ns) as gm:
        do(gm, "pc_add", name="Vex")
        do(gm, "npc_add", name="Secret Boss", visible=False)
        do(gm, "npc_add", name="Town Guard", visible=True)
        do(gm, "log_note", text="ambush plan: they never suspect the mule")
        pc_id = state["party"][0]["pc_id"]

        with player_session(ns, "dev-hide") as pws:
            pending = pws.recv()
            assert pending["state"]["status"] == "pending"
            assert "gm_token" not in pending["state"]  # every role's frames are clean
            gm.recv()
            gm.send(type="action", action="approve_join", args={"device_token": "dev-hide", "pc_id": pc_id})
            view = pws.recv()["state"]
            names = [n["name"] for n in view["npcs"]]
            assert "Secret Boss" not in names and "Town Guard" in names
            assert all(e["audience"] == "all" for e in view["log"])
            assert not any("ambush plan" in e["text"] for e in view["log"])


def test_ping_pong_clock_sync(ns):
    with WS(ns.ws_base + "/ws") as ws:
        ws.send(type="ping")
        pong = ws.recv()
        assert pong["type"] == "pong" and abs(pong["server_time"] - time.time()) < 30


def test_snapshot_survives_restart(tmp_path):
    data_dir = str(tmp_path)
    with TestServer(data_dir, fresh=True) as srv:
        state = srv.app.state_model
        actions.apply_action(state, "gm", "GM", "pc_add", {"name": "Vex"})
        actions.apply_action(state, "gm", "GM", "pc_hearts", {"pc_id": state["party"][0]["pc_id"], "delta": -1})
        # a Room commit saves; here we drove the state directly, so save explicitly
        from server import state as st

        st.save_snapshot(state, data_dir)
        room_code, gm_token, version = state["room_code"], state["gm_token"], state["version"]

    with TestServer(data_dir, fresh=False) as srv2:
        state2 = srv2.app.state_model
        assert state2["room_code"] == room_code
        assert state2["gm_token"] == gm_token  # GM's browser session survives too
        assert state2["version"] == version
        assert state2["party"][0]["name"] == "Vex"
        assert state2["party"][0]["hearts"] == state2["party"][0]["hearts_max"] - 1

    with TestServer(data_dir, fresh=True) as srv3:
        assert srv3.app.state_model["party"] == []


# -- hub robustness over the wire (ticket 32) ---------------------------------


def test_malformed_frames_get_errors_not_disconnects(ns):
    with gm_session(ns) as gm:
        for frame in ['"x"', "[1]", "null", "123", '{"type":123}', '{"type":"action","args":"nope"}']:
            gm.ws.send(frame)
            msg = gm.recv()
            assert msg["type"] == "error", frame
        # the socket survived every malformed frame and still works
        state = do(gm, "log_note", text="still here")
        assert state["log"][-1]["text"] == "still here"


def test_wrong_typed_action_args_get_errors(ns):
    with gm_session(ns) as gm:
        for action, args in [
            ("set_targets", {"default": "12a", "scene": 3}),
            ("pc_hearts", {"pc_id": "pc_x", "delta": "abc"}),
            ("pc_hearts", {"pc_id": "pc_x", "delta": True}),
            ("pc_hearts", {"pc_id": "pc_x", "delta": 10**400}),  # OverflowError class
            ("milestone_delete", {"index": "x"}),
            ("pc_update", {"pc_id": "pc_x", "hearts_max": True}),
        ]:
            gm.send(type="action", action=action, args=args)
            msg = gm.recv()
            assert msg["type"] == "error", (action, args)
        do(gm, "log_note", text="alive")  # the connection survived them all


def test_watcher_survives_dead_conn(ns):
    # the ticket 32 kill scenario: a broadcast to a dead socket used to be
    # able to kill the timer watcher, silently stopping alarm resolution
    from server.hub import Connection

    class FailingWS:
        async def send_text(self, text):
            raise RuntimeError("simulated dead socket")

    room = ns.app.state_room
    with gm_session(ns) as gm:
        state = do(gm, "timer_add", kind="alarm", label="boom", duration_s=2)
        do(gm, "timer_start", timer_id=state["timers"][0]["timer_id"])
        dead = Connection()
        dead.ws = FailingWS()
        dead.role = "gm"
        room.conns.append(dead)  # dies right before the watcher's next tick

        # the alarm must still ring on the REAL client — with no action sent,
        # the only broadcaster is the watcher itself
        deadline = time.time() + 10
        alarm_seen = False
        while time.time() < deadline and not alarm_seen:
            msg = gm.recv(timeout=10)
            if msg["type"] == "state" and msg["state"].get("alarm"):
                alarm_seen = True
        assert alarm_seen, "watcher died before ringing the alarm"
        # the reap happens in the same broadcast that delivered the alarm, but
        # asynchronously relative to this thread — poll, don't race
        deadline = time.time() + 5
        while dead in room.conns and time.time() < deadline:
            time.sleep(0.05)
        assert dead not in room.conns, "dead conn was never reaped"
        do(gm, "log_note", text="watcher alive")  # server fully functional


# -- join/reject lifecycle (ticket 33) ----------------------------------------


def test_reject_join_notifies_and_sticks(ns):
    with gm_session(ns) as gm:
        with player_session(ns, "dev-rej", name="Lurker") as pws:
            pws.recv()  # pending
            gm.recv()   # the knock

            gm.send(type="action", action="reject_join", args={"device_token": "dev-rej"})
            gm.recv()  # the reject broadcast

            # the rejected socket gets its refusal painted, then a 4003 close
            refusal = pws.recv()
            assert refusal["type"] == "state"
            assert refusal["state"].get("rejected") is True
            _assert_closed_with(pws, 4003)

        # a reload re-hellos with the same token: still rejected, and the
        # knock panel must NOT see them again
        with player_session(ns, "dev-rej", name="Lurker") as pws2:
            again = pws2.recv()
            assert again["state"]["status"] == "pending"
            assert again["state"].get("rejected") is True
            gm_view = do(gm, "log_note", text="probe")
            assert not any(r["device_token"] == "dev-rej" for r in gm_view["join_requests"])

        assert any(r["device_token"] == "dev-rej" for r in ns.state["rejections"])

        # the GM can still explicitly seat a rejected device
        do(gm, "pc_add", name="Second")
        pc_id = ns.state["party"][0]["pc_id"]
        with player_session(ns, "dev-rej", name="Lurker") as pws3:
            pws3.recv()  # pending + rejected, no knock
            gm.send(type="action", action="approve_join", args={"device_token": "dev-rej", "pc_id": pc_id})
            seated = pws3.recv()["state"]
            assert seated["you"]["pc_id"] == pc_id
        assert "dev-rej" not in ns.state["rejections"]


def test_stale_snapshot_knock_pruned_on_boot(tmp_path):
    from server import state as st

    s = st.new_state("ROOM", "tok")
    s["join_requests"].append({"device_token": "ghost", "name": "Ghost"})
    st.save_snapshot(s, str(tmp_path))

    with TestServer(str(tmp_path), fresh=False) as srv:
        # the knocking client is long gone — the ghost must not linger
        assert srv.app.state_model["join_requests"] == []
