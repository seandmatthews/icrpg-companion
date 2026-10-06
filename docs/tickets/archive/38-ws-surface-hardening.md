# 38 — WS surface hardening: pre-auth disclosure, handler robustness, knock abuse

**Status:** completed — implemented and code-reviewed 2026-10-06 (three review rounds; round 2 caught a flaky test and a guard-coverage claim that didn't hold).
**Priority:** P2
**Area:** `server/app.py` (ws handler, bootstrap), `server/hub.py`
(broadcast, join_requests)
**Found by:** 2026-10-06 full adversarial review

## Problem

One coherent surface — everything a socket can do before/at
authentication — with a mix of severities:

1. **Never-helloed sockets receive pending-view broadcasts.** Conns
   are appended immediately on accept (`app.py:87`) and `broadcast()`
   fans out to all conns with no role floor (`hub.py:62-70`);
   `role=None` maps to the pending view (`hub.py:58`). Any socket that
   connects and says nothing — a port scanner, or a drive-by webpage
   doing cross-site WebSocket hijacking from the GM's own browser
   (`ws://localhost:8770/ws`; no Origin check) — passively receives
   the room title and all party character names on every broadcast,
   bypassing the knock/approve gate. Invisible disclosure.
2. **Non-disconnect send failures abort the handler.** Every direct
   `send` in the loop (`app.py:93, 98, 102, 107, 117, 138, 143`) sits
   outside the `except WebSocketDisconnect` guard; a send failing on a
   socket that just died raises a different exception, escaping the
   loop as an unhandled error (uvicorn traceback, no error frame).
   The `finally` still cleans up — this is about the contract and the
   log noise, not a leak.
3. **GM key compared with `!=`** (`app.py:101`), not
   `secrets.compare_digest`; no rate limit on failed `hello_gm`.
   LAN-only makes exploitation implausible — hygiene.
4. **Unbounded knock list, disk commit each.** `hello_player` appends
   and commits per unique token (`hub.py:100-102`); a scripted loop of
   unique tokens floods the GM panel and grows every future snapshot
   write.
5. **Server mints `device_token`s it never returns** (`app.py:115`):
   a tokenless hello becomes a permanently un-reconnectable identity
   that re-knocks on every reconnect. Related: tokens are
   client-chosen, so a *learned* token impersonates a player (the
   trust decision lives in `hub.py:88-102`).
6. **`/api/bootstrap` hands `room_code` to any unauthenticated
   caller** (`app.py:69-80`) — the room code is the sole player
   credential, so the QR is redundant on a scanned network. Fine on a
   trusted LAN **if that stance is documented** — needs a user ruling.

## Proposal

- Skip `role is None` conns in `broadcast`/`send_to` fan-out; close
  sockets that haven't hello'd within a few seconds (deadline in the
  existing watcher or a receive timeout).
- Wrap the per-message send paths (or the whole loop body) in a broad
  `except Exception` treated as disconnect, falling through to the
  existing `finally`.
- `secrets.compare_digest` for the GM key; cap `join_requests`
  (e.g. 50, oldest evicted).
- Return the assigned token in the hello response *or* reject
  tokenless hellos; consider validating token shape/length.

## Ruling (do not revisit)

Bootstrap `room_code` disclosure (2026-10-06): **document the
trusted-LAN stance — keep returning the room code unauthenticated.**
The room code is a convenience (saves typing), not a secret; the
network is the outer gate and the GM's knock-approval is the real
boundary. Anyone on the LAN can knock with any name regardless, so
hiding the code adds friction without adding a boundary. Gating the
code behind the GM key is the known escape hatch if the venue threat
model ever changes (semi-public Wi-Fi); re-litigate only then.

## Acceptance criteria

- [ ] `tests/test_ws_flow.py::test_silent_socket_receives_no_state` —
      open a raw WS, send nothing; a GM client performs an action;
      within a short window the silent socket receives **no** state
      frame (recv timeout fires). Today it receives every broadcast.
- [ ] `tests/test_ws_flow.py::test_unhelloed_socket_is_closed` — the
      silent socket is closed by the server within the hello deadline
      (recv raises/times out), and the server stays healthy for other
      clients.
- [ ] `tests/test_ws_flow.py::test_client_drop_during_send_is_quiet`
      — a client that disconnects immediately after triggering an
      action produces no unhandled traceback in the server log
      (capture caplog/stderr during the exchange) and other clients
      keep receiving broadcasts.
- [ ] `tests/test_ws_flow.py::test_join_request_cap` — flood more
      hello-knocks than the cap from distinct tokens: the list length
      stays at the cap, the GM panel still works, the server is
      responsive.
- [ ] `tests/test_ws_flow.py::test_tokenless_hello_gets_token` — pin
      the chosen contract: a hello without `device_token` either
      receives one back (and reconnecting with it restores the seat)
      or is rejected with an ActionError-style frame.
- [ ] DESIGN.md carries the trusted-LAN stance paragraph (network is
      the outer gate, GM approval is the real boundary; the room code
      is a convenience, not a secret) — the doc line lands with this
      ticket.

## Implementation notes (2026-10-06)

Landed in `server/hub.py`, `server/app.py`, `DESIGN.md` (§10 ruling
paragraph), `tests/test_ws_flow.py`:

- Pre-auth disclosure closed: broadcast fan-out skips role-None conns, and
  the watcher sweeps never-helloed sockets with `close(4000)` after
  `HELLO_DEADLINE` (10s; sweep runs AFTER timer authority so a failing close
  never delays an alarm). Pinned by `test_silent_socket_receives_no_state`
  and `test_unhelloed_socket_is_closed`.
- Cross-site Origin handshakes (incl. `Origin: null`) refused pre-accept;
  absent Origin (non-browser) allowed per the LAN stance. The legitimate
  client can never be rejected (its Origin netloc == Host by construction).
- Handler robustness: the whole per-message dispatch (parse, shape checks,
  sends) sits inside one guard — `except WebSocketDisconnect: raise` /
  `except Exception: log + return` — so a failing send to a dying socket is
  a quiet reap, never an unhandled ASGI error. Pinned by
  `test_client_drop_during_send_is_quiet` (caplog: zero ERROR records).
- GM key compared via `secrets.compare_digest` on utf-8 bytes (non-ASCII
  keys now get the readable "wrong GM key", not a TypeError).
- Knock flood capped: `KNOCK_CAP = 50`, oldest evicted, via the shared
  `Room._record_knock` used by hello AND demotion re-knocks. Pinned state-
  level with a monkeypatched cap of 5.
- Tokenless hello_player rejected (readable error + 4002 close) — the
  server-minted ghost-identity path is gone; every real client mints its own
  token client-side (ticket 34).
- Deviations (documented): the tokenless contract landed as REJECT rather
  than return-the-minted-token (cleaner identity model, no client impact);
  no per-conn knock rate limit — the cap bounds the damage. The GM stale-
  room cache flash residual stays with tickets 40/41.
- Three review rounds: round 2 caught a flaky AC test (2s recv racing the
  sweep) and that a patch had not actually moved the garbled-message sends
  inside the guard — both fixed; the ws loop was rewritten cleanly in one
  piece after patch damage. Gates: `python -m pytest` — 79 passed ×3.
