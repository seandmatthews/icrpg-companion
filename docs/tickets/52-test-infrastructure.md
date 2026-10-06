# 52 — test infrastructure: leak-proof boots and false greens

**Status:** proposed
**Priority:** P2
**Area:** `tests/test_ws_flow.py`, `tests/test_actions.py`,
`scripts/make_icons.py`
**Found by:** 2026-10-06 full adversarial review

## Problem

The suite's harness can leak and two of its assertions are false
greens:

1. **`test_snapshot_survives_restart` boots three servers with no
   try/finally** (`test_ws_flow.py:212-236`): an assertion failure
   mid-test abandons live `uvicorn.Server` daemon threads holding
   listening sockets and open `state.json` files — on Windows,
   poisoning later runs via `tmp_path` cleanup failures, silently
   (the daemon keeps "working").
2. **`shutdown()` swallows a stalled join.** `thread.join(timeout=5)`
   with no `is_alive()` check (`test_ws_flow.py:38-40`) — a uvicorn
   stuck on open WS connections half-dies silently.
3. **WS clients aren't closed on assertion failure.** Every test
   closes `gm`/`pws` as its last statements, no try/finally
   (`:135-156, 167, 200-209`); cleanup depends on server shutdown
   reaping them before the join expires.
4. **`boot()` failure leaks the thread** (`:29-35`): if `started`
   never flips, the RuntimeError leaves a possibly-still-binding
   daemon behind.
5. **False greens.** `test_rejoin_restores_seat_without_new_request`
   never reads a GM view — a regression re-appending knocks on
   re-hello keeps it green (`:139-156`). The negative role-wall tests
   all fail via the blanket `else` ("unknown player action"),
   not an ownership check (`test_actions.py:22-29, 84-94`) — a
   refactor routing pc verbs through a permissive player path stays
   green. `gm_token` absence is asserted against `/api/bootstrap`
   but never against any WS state frame.
6. **Odds:** dead `import socket` (`test_ws_flow.py:9`); the
   wrong-key test doesn't assert the 4001 close actually happens
   (`:101-105`); `make_icons.py` writes its three committed PNGs by
   truncate-in-place (`scripts/make_icons.py:27-28`) — the one file
   in the repo not following the tmp+`os.replace` discipline.

## Proposal

- Make boot/shutdown a context manager (or fixture) that closes
  clients, shuts down, and **fails if the thread is alive**; convert
  the manual three-boot test to it.
- try/finally client closes everywhere (or a small `ws_client()`
  context manager).
- Fix the false greens: assert `join_requests == []` on the GM view
  after rejoin; rename or re-anchor the role-wall tests to a real
  ownership path (e.g. `player_return` on another PC's item — which
  exists); add `assert "gm_token" not in <player state frame>`.
- Atomic icon writes; drop the dead import; assert the 4001 close.

## Acceptance criteria

- [ ] The harness itself is pinned: a deliberately failing test
      (marked/parametrized, or a local run note) leaves no live
      server thread — asserted via a module-level registry of booted
      servers checked in a session finalizer (`test_ws_flow.py::
      test_no_leaked_servers_after_failure`).
- [ ] `shutdown()` fails loudly: a monkeypatched never-dying server
      thread makes `shutdown()` raise instead of returning silently.
- [ ] `tests/test_ws_flow.py::test_rejoin...` (amended) — after the
      re-hello, the GM's next frame shows `join_requests == []`
      (today: not checked).
- [ ] `tests/test_actions.py::test_player_return_other_pc_item_rejected`
      — the ownership wall asserted through a real player action, not
      the else-branch; the `test_player_cannot_call_gm_actions` names
      updated to what they actually pin.
- [ ] `tests/test_ws_flow.py::test_gm_token_absent_from_ws_frames` —
      every role's first state frame lacks `gm_token` (today: only
      bootstrap is checked).
- [ ] Wrong-key test asserts the server closes with 4001 (recv
      raises/close code observed), not just the error frame.
- [ ] `make_icons.py` uses tmp + `os.replace`; `import socket` gone;
      full suite green with no new warnings.
