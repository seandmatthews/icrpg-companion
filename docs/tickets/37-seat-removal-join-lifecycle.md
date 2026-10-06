# 37 — seat-removal join lifecycle: knockless limbo and the two-tab knock

**Status:** proposed
**Priority:** P2
**Area:** `server/hub.py` (refresh_seats, handle_hello_player),
`server/app.py` (ws finally), extends ticket 33
**Found by:** 2026-10-06 full adversarial review

## Problem

Two defects in how seats die while players are connected (traced
independently by three review lanes):

1. **`pc_delete` / `session_reset` orphan the connected player.**
   Both remove the binding (`actions.py:200-206`, `:345-349`) but
   create no join request. On the next broadcast, `refresh_seats`
   (`hub.py:38-52`) demotes the still-connected conn to
   `role="pending"` — but join requests are only ever appended in
   `handle_hello_player` (`hub.py:100-102`), i.e. on a fresh hello.
   The player's phone flips to "Knock knock… Waiting for the GM"
   while the GM's knock panel is **empty**: nobody can seat the
   player, and `approve_join` fails with "no such join request" if the
   GM tries. Recovery requires the player to think of reloading.
   `session_reset` does this to the whole table at once.
2. **Closing one of two tabs kills the live knock.** Two tabs of the
   same device share one `device_token` and one `join_requests`
   entry; the ws `finally` drops the request on any pending
   disconnect (`app.py:151-153`), so closing the *spare* tab removes
   the knock while a live pending player still waits.

Adjacent to ticket 33 (P3-42 reject/reload, P3-44 stale snapshot
knocks) but a different trigger: seats removed by GM actions and the
multi-tab variant, not reject or restart.

## Proposal

- In `refresh_seats`, on the transition bound → pending for a conn
  with a `device_token`, append the join request (same dedup as
  hello) and `broadcast_to_gms` so the knock panel populates.
- In the ws `finally`, drop the join request only when no *other*
  live conn in `room.conns` holds the same `device_token`.

## Acceptance criteria

- [ ] `tests/test_ws_flow.py::test_pc_delete_reknocks_connected_player`
      — GM + seated player over WS; GM sends `pc_delete`; the player's
      next state frame is `pending` AND the GM's next frame contains a
      join request for that device token; `approve_join` then succeeds
      and the player is seated again — all without the player
      reloading.
- [ ] `tests/test_ws_flow.py::test_session_reset_reknocks_players` —
      same flow for `session_reset` with two seated players: both
      appear as knocks after the reset broadcast.
- [ ] `tests/test_ws_flow.py::test_closing_second_tab_keeps_knock` —
      two pending sockets hello with the same `device_token` + name;
      close one; the GM view still lists the join request; close the
      other; the request is dropped (commit trimmed).
- [ ] `tests/test_ws_flow.py::test_reject_after_reknock_still_sticks`
      — regression guard tying into ticket 33: after a re-knock caused
      by `pc_delete`, `reject_join` removes it (no duplicate knock
      accumulation across repeated delete/re-seat cycles).
