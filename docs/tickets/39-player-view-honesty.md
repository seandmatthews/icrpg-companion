# 39 — player-view honesty: countdowns, table log, hush, claim rollback

**Status:** proposed
**Priority:** P2
**Area:** `client/src/components/Timers.tsx`, `client/src/util.ts`
(timerRemainSec), `client/src/views/PlayerView.tsx`
**Found by:** 2026-10-06 full adversarial review

## Problem

Four places where the player's phone shows something other than the
server truth, plus one dead end:

1. **Paused and done timers display their full duration.**
   `timerRemainSec` returns `null` for anything not `running`
   (`util.ts:125-132`), and `Countdown` then renders
   `timer.duration_s ?? 0` (`Timers.tsx:15-17`). A 10-minute timer
   paused at 7:00 remaining reads **10:00** in idle styling on every
   phone; a `done` timer flips back to full duration after ringing,
   implying it never ran. Only the GM console has a tiny "paused"
   label; the player list has no state chip at all.
2. **Players never see the table log.** The server already filters
   audience-`"all"` entries into the player view (`state.py:190`) —
   including the GM's "players see it" notes and the claim
   announcements — and `PlayerView` never renders `view.log`. The GM
   believes the table read the note; no player can.
3. **Hush permanently kills that timer's future rings.** `hushed`
   stores one `timer_id` and is never cleared
   (`PlayerView.tsx:42, 63, 67`); the server re-alarms with the same
   `timer_id` after reset/restart (`actions.py:151-159`). A player who
   hushed once gets nothing on every later ring — the overlay is the
   player-facing point of the alarm feature. (Found independently by
   two lanes.)
4. **Claim "in progress" never rolls back.** `setClaiming(true)` with
   no reset path (`PlayerView.tsx:10-25`): a dropped or rejected claim
   leaves the card permanently dimmed at half opacity, still showing a
   Claim button; a fast double-tap makes the player see a red "already
   claimed" toast for *their own successful claim*.
5. **"Your seat vanished" is a dead end** (`PlayerView.tsx:58`) — no
   button, no hint that reloading re-enters the knock flow; recovery
   is close-the-PWA folklore.

## Proposal

- `Countdown`: when `paused`, render `duration_s -
  elapsed_before_pause`; when `done`, render `0:00` (or "rang"); idle
  keeps full duration. Add a small state chip (paused/done) to the
  player timer rows.
- Add a compact "Table" section to `PlayerView` rendering
  `view.log ?? []`.
- Clear `hushed` whenever `view.alarm` becomes null (or key it by
  `(timer_id, started_at)`) so only the current ring can be hushed.
- Reset `claiming` on the next error or state echo; disable the
  button while claiming; suppress the "already claimed" toast when the
  claim actually succeeded (or reword server-side to "you already
  hold this").
- Replace the dead-end text with a "Knock again" button that clears
  the local seat and re-hellos (pairs with ticket 37's server-side
  re-knock).

## Acceptance criteria

Client defects are browser-gated — each is surfaced by a named manual
click-through (per CONVENTIONS, that is the pinning check), plus the
one server-side assertion that guards the log payload:

- [ ] Manual: start a 10:00 alarm, pause it around 7:00 → the player
      phone shows ≈3:00 with a paused chip (not 10:00); let a timer
      ring → player rows show 0:00/"rang", not the full duration.
- [ ] Manual: GM posts a note with "players see it" ticked and claims
      loot as a player → both appear in the player's Table section
      within one broadcast; a GM-only note does not.
- [ ] `tests/test_actions.py::test_claim_announcement_is_player_audience`
      — the log entry `player_claim` appends has `audience: "all"`
      (pins the server half the new UI consumes; today it is true only
      by inspection).
- [ ] Manual: hush a ringing alarm → GM resets and restarts the same
      timer → it rings again on that phone (overlay appears).
- [ ] Manual: stop the server, tap Claim → the card returns to normal
      styling after the failure surfaces (not stuck dimmed); with the
      server up, double-tap Claim fast → exactly one toast, and it
      does not read as a failure of the successful claim.
- [ ] Manual: GM deletes the seated PC → the player's dead-end screen
      has a working "Knock again" affordance that produces a knock in
      the GM panel.
- [ ] `npm run build` green.
