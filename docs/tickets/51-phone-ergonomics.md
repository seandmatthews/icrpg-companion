# 51 — phone ergonomics of failure-critical surfaces

**Status:** proposed
**Priority:** P3
**Area:** `client/src/styles.css`, `client/src/components/Hearts.tsx`,
`Timers.tsx`, `client/index.html`
**Found by:** 2026-10-06 full adversarial review

## Problem

Layout facts that make *failure* and *play* surfaces unreliable on
the phones this app targets (functional issues only, not aesthetics):

1. **No safe-area insets despite `viewport-fit=cover`**
   (`client/index.html`; no `env(` anywhere in `styles.css`): the
   error toast — the only failure channel — sits at `bottom: 1rem`
   (`styles.css:741-746`) and can render partially under the iPhone
   home indicator, exactly when things go wrong; the player view
   padding lacks insets (`:766-769`); `min-height: 100vh` (`:68-74`)
   misbehaves with the Safari URL bar (use `100dvh`).
2. **The hearts row overflows the phone at high max.** No wrap on the
   player stepper (`styles.css:789-794`), 2.3rem cells
   (`:197-199`), every cell rendered up to max (`Hearts.tsx:18`;
   the numeric fallback only kicks in above 20): at 14–16 hearts
   (server allows 20, `actions.py:181`) the row overflows a 375 px
   card and the damage button can be pushed off-screen — the
   player's primary control becomes unreadable/un-tappable.
3. **28 px touch targets on wrong-play-prone buttons.** `btn-sm` and
   the heart steppers sit below comfortable size (`styles.css:140-144`)
   — mis-taps between damage and heal are real play errors.
4. **Urgency styling is inverted.** Player phones get the ≤30 s
   `timer-hot` treatment (`Timers.tsx:24-26`); the GM console — the
   person who must *react* — does not (`Timers.tsx:46`).

## Proposal

- `padding: env(safe-area-inset-*)` on `.toast`, `.player-view`,
  footer; `min-height: 100dvh`.
- Hearts: wrap or scale cells by count; switch to numeric + small
  pips above ~10–12; enlarge the stepper buttons on the player view.
- Apply the `urgent` computation to `TimerGM` (reuse `TimerStatus`'s).

## Acceptance criteria

Browser-gated; pinned by named manual click-throughs plus the build
gate:

- [ ] Manual (notched iPhone or devtools device mode with safe-area
      simulation): trigger an error toast → fully visible above the
      home indicator; the player footer likewise.
- [ ] Manual: a 16-heart PC on a 375 px-wide phone → all hearts and
      both stepper buttons visible and tappable without horizontal
      scroll; a 20-heart PC falls back to the numeric display
      gracefully.
- [ ] Manual: damage/heal steppers ≥ ~44 px effective touch target on
      the player view.
- [ ] Manual: a timer inside 30 s shows the hot styling on the GM
      console as well as the player list.
- [ ] `npm run build` green.
