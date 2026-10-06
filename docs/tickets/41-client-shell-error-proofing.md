# 41 — client shell error-proofing: boundary, cache validation, storage, logout

**Status:** proposed
**Priority:** P2
**Area:** `client/src/main.tsx`, `client/src/net.ts` (cache), 
`client/src/util.ts`, `client/src/App.tsx`, `README.md` (PWA wording)
**Found by:** 2026-10-06 full adversarial review

## Problem

The client shell has no floor under it — anything unexpected becomes
a bare white screen on a phone, mid-session:

1. **No error boundary, no global handlers.** `main.tsx:6-10` is a
   bare `createRoot(...).render(...)`; there is no
   `ErrorBoundary`/`componentDidCatch`, no `window.onerror`, no
   `unhandledrejection` anywhere in `client/src`. One thrown render
   error = blank page with no reload prompt.
2. **The cached view is blind-cast.** `net.ts:24` does
   `cachedView() as StateView` with zero validation
   (`util.ts:58-65` parses to `unknown`, the caller asserts), and the
   client never checks the `schema` field its own type declares
   (`types.ts:64`). An old-shape or hand-corrupted cache throws on
   first paint (`view.timers.map(...)`) — into defect 1's white
   screen. Distinct from ticket 33's scoping item: even a correctly
   scoped cache is unvalidated.
3. **Mixed guarded/unguarded localStorage helpers.** `getSeat` and the
   cache pair are try/caught; `getDevice`, `getGmKey`/`setGmKey`,
   `setSeat`, `clearCachedView` are not (`util.ts:13-48, 67-69`). In
   Safari private mode or at quota, a `setItem` throw inside a React
   event handler (`onKey` calls `setGmKey` before any state update) =
   white screen.
4. **No GM logout.** `setGmKey(null)` is reachable only via the
   auth-fail callback (`App.tsx:135`, `util.ts:26-29`): once a key is
   entered, the browser is a GM console forever without DevTools; a
   seat holder can't get back to Landing either.
5. **Two tabs, no coordination.** No `storage`-event handling; storage
   is read once at mount (`App.tsx:135-140`). With both a GM key and a
   player seat stored, root `/` always resolves to the GM console with
   no documented path to the seated player view (GM-key-wins
   precedence is implicit).
6. **"PWA" overpromises.** Manifest + icons only; no service worker,
   and installability is impossible over LAN HTTP (insecure context).
   README's "Add to Home Screen" line should say what actually
   happens.
7. **`useWakeLock` can leak a late lock** (`util.ts:91-110`): the
   acquire promise can resolve after cleanup; the lock is then set
   post-unmount and never released (browsers release on tab hide, so
   low impact).

## Proposal

- Minimal top-level `ErrorBoundary` class + `window` error/unhandled
  rejection listeners rendering "something broke — tap to reload".
- Validate the parsed cache before the cast: `schema ===
  "table-companion/v0"`, `typeof version === "number"`, plus the
  fields the instant-paint path touches; clear-on-mismatch.
- Wrap all storage helpers best-effort (treat storage as optional,
  like the cache already does).
- A "forget this console" action on the GM session card (clears
  key/view, returns to Landing); document the GM-key-wins precedence
  (or add a route picker).
- README wording fix; re-check `cancelled` after the `await` in
  `useWakeLock` and release.

## Acceptance criteria

- [ ] Manual: corrupt `tc_view` in devtools (valid JSON, wrong shape,
      e.g. `{"schema":"nope"}`) → the app boots to the join/key form,
      not a white screen, and the bad cache is cleared from storage.
- [ ] Manual: trigger a render error (temp throw in a dev build) → the
      boundary card with a working reload affordance appears instead
      of a blank page; `window.onerror`-style async rejection likewise
      surfaces rather than vanishing.
- [ ] Manual: in a private-mode window (or with storage mocked to
      throw), joining and playing a full hand works — no crash;
      behavior degrades to session-only storage.
- [ ] Manual: "forget this console" clears the GM identity and lands
      on the landing screen; a subsequent reload stays logged out.
- [ ] If the plain-node harness from ticket 52 lands, the cache
      validator is extracted pure and pinned with `node --test`
      (`test_validate_view_cache.mjs`: wrong schema → reject, short
      object → reject, valid → pass).
- [ ] README's Add-to-Home-Screen line states the actual behavior over
      LAN HTTP; `npm run build` green.
