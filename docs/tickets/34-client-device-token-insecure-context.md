# 34 — client: device token minting is broken on phones (insecure context)

**Status:** proposed
**Priority:** P1
**Area:** `client/src/util.ts` (getDevice), `client/src/net.ts` (hello path)
**Found by:** 2026-10-06 full adversarial review

## Problem

`getDevice()` mints the device token with `crypto.randomUUID()`
(`client/src/util.ts:16`), called unguarded inside the WebSocket
`onopen` handler before the hello is sent (`client/src/net.ts:47,51`).
`crypto.randomUUID` exists **only in secure contexts** (HTTPS or
localhost) in Chrome, Safari, and Firefox alike. The server serves
plain `http://<lan-ip>:8770` (`run.py`), so every phone that scans the
QR is an insecure context.

First visit from a phone: `TypeError: crypto.randomUUID is not a
function` thrown inside `onopen` — *after* `setStatus("open")` already
ran. The hello is never sent, the socket is healthy so nothing
reconnects, and the player sees a green dot plus "Knock knock…"
forever, with no toast and no error anywhere. The laptop at
`localhost` is a secure context, which is why desk testing passes.
The product's primary flow is likely dead on arrival on real phones.

## Proposal

Replace the mint with a context-safe fallback:

- If `crypto.randomUUID` exists, use it; otherwise format 16 bytes
  from `crypto.getRandomValues` (available in insecure contexts) as a
  UUID-shaped hex string.
- Wrap the `getDevice()` body in try/catch so a storage/crypto failure
  degrades to an in-memory token for the session instead of throwing
  in `onopen`.
- `console.warn` (not throw) on the fallback path.

## Acceptance criteria

- [ ] Fallback minting is a pure, testable function (bytes → token).
      If the plain-node harness from ticket 52 exists, pin it with
      `node --test` on the compiled helper: given a stubbed
      `crypto.getRandomValues`, it returns a UUID-shaped string; given
      no `crypto.randomUUID`, it does not throw. (`tsc` alone cannot
      surface this defect — it is runtime-context-gated.)
- [ ] Manual click-through (the real surfacing test): with empty
      browser storage, open `http://<lan-ip>:8770/join` from a device
      that is **not** localhost (phone on the LAN, or a desktop browser
      pointed at the machine's LAN IP). The seat form must submit and
      the server must log the hello (knock appears in the GM panel).
      Before the fix, this exact procedure hangs at "Knock knock…" with
      a console TypeError.
- [ ] Manual: reload the page after joining — the seat restores
      (token persisted), proving the fallback token round-trips
      through localStorage and the server binding.
