"""Ticket 47: LAN-IP detection ranking + once-at-boot injection."""

from server.app import _rank_candidates, detect_lan_candidates


def test_detection_ranks_ranges():
    ranked = _rank_candidates(["172.20.0.5", "10.0.0.2", "192.168.1.10"])
    assert ranked[0] == "192.168.1.10"
    # a 172.16-31-only set resolves to it rather than the hostname fallback
    assert _rank_candidates(["172.20.0.5", "172.16.9.9"]) == ["172.20.0.5", "172.16.9.9"]
    # a virtual Docker adapter never outranks a home LAN
    assert _rank_candidates(["172.17.0.1", "192.168.0.15"])[0] == "192.168.0.15"
    # unknown ranges keep input order after the ranked ones
    assert _rank_candidates(["100.64.0.1", "10.9.9.9"]) == ["10.9.9.9", "100.64.0.1"]


def test_detection_is_total_and_live():
    # the real probe still runs (no injection) and returns a list of strings
    result = detect_lan_candidates()
    assert isinstance(result, list)
    assert all(isinstance(ip, str) for ip in result)


def test_bootstrap_does_not_detect(tmp_path, monkeypatch):
    # the blocking DNS/probe path runs ONCE at boot, never per request —
    # per-request detection froze the whole event loop (ticket 47)
    import json
    import urllib.request

    from server import app as app_module
    from test_ws_flow import TestServer

    calls = {"n": 0}
    real = app_module.detect_lan_candidates

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(app_module, "detect_lan_candidates", counting)

    srv = TestServer(str(tmp_path))
    try:
        http_base = srv.ws_base.replace("ws://", "http://")
        for _ in range(5):
            with urllib.request.urlopen(http_base + "/api/bootstrap", timeout=5) as r:
                json.loads(r.read())
        # neither create_app nor /api/bootstrap ever probes — run.py owns the
        # single boot-time call, so a request can never freeze the loop
        assert calls["n"] == 0
    finally:
        srv.close()
