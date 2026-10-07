# 47 — LAN IP detection: wrong adapter, blocking DNS on the loop, DHCP staleness

**Status:** completed — implemented 2026-10-06 (boot-path work rode ticket 46's lane, named there); tests + review this lane.
**Priority:** P3
**Area:** `server/app.py` (detect_lan_ip, /api/bootstrap), `run.py`
(banner)
**Found by:** 2026-10-06 full adversarial review

## Problem

1. **The detection can pick an adapter phones can't reach, silently.**
   `detect_lan_ip` (`app.py:22-49`) ranks only `192.168.` and `10.`
   prefixes; a real LAN on `172.16-31.x` (also what WSL/Hyper-V/Docker
   virtual adapters use) falls through to `candidates[0]` or
   `gethostbyname(hostname)` — which can be a virtual or non-routable
   address. The banner prints a confident wrong URL and the QR
   encodes it; phones time out and nothing logs anything. The
   docstring claims "home-LAN ranges beat VPN/Tailscale" but
   `172.16-31` is neither excluded nor ranked.
2. **Blocking DNS on the event loop, per request.** The async
   `/api/bootstrap` handler calls `socket.gethostbyname`
   (`app.py:40, 78`) — on Windows with VPN adapters or broken DNS
   search lists this can stall **seconds**, freezing live WS
   broadcasts and the timer watcher for that duration. (The boot-time
   call in `run.py` is fine; the per-request one is the defect.)
3. **DHCP renewal staleness is undisclosed.** The QR is regenerated on
   every "Show QR", but the banner URL and any QR opened before a
   mid-session IP change silently point at the old address.

## Proposal

- Compute `lan_ip` once at startup in `run.py` and pass it into
  `create_app` (also fixes the blocking-call defect for free).
- Rank `172.16-31` (excluding the obvious virtual ranges or ranking
  them last), and when candidates are ambiguous print **all** of them
  in the banner with a "pick the one your phone's Wi-Fi reaches" hint.
- One banner line noting the join URL is boot-time (restart or re-open
  Show QR after a network change).

## Acceptance criteria

- [ ] `tests/test_app_lan_ip.py::test_detection_ranks_ranges` (new) —
      with `detect_lan_ip` refactored for injection (candidate list /
      route-probe as parameters), a candidate set containing a
      `172.20.x` virtual adapter, a `192.168.x`, and a `10.x` resolves
      to the ranked choice; a `172.16-31`-only set resolves to it
      rather than the hostname fallback.
- [ ] `tests/test_app_lan_ip.py::test_bootstrap_does_not_detect` —
      monkeypatch a counter around `detect_lan_ip`; boot once, hit
      `/api/bootstrap` five times → the counter stays at the startup
      call count (no per-request detection, hence no blocking DNS on
      the loop).
- [x] Banner ambiguity: with multiple candidates injected, the banner
      lists them all (pure `banner_lines()` helper test if extracted
      per ticket 46's pattern, else manual).

## Implementation notes (2026-10-06)

- Ranking: 192.168 > 10.x > 172.16-31 (ranked LAST — real networks live
  there, but so do WSL/Hyper-V/Docker adapters) > input order. Extracted as
  pure `_rank_candidates` with an isdigit octet guard; pinned by a table
  test including the AC's 172-only and Docker scenarios.
- Once-at-boot: run.py computes candidates and injects `lan_ip` into
  create_app; /api/bootstrap serves the closure value. `test_bootstrap_
  does_not_detect` pins the structural fact (a counting monkeypatch stays
  at zero through five requests). The alternates line and the boot-time
  note are pinned in test_banner_lists_alternates_and_boot_note; the
  injection value by test_create_app_injects_lan_ip (TestServer gained a
  lan_ip kwarg).
- Deviation: the AC's "print all candidates with a pick-the-right-one hint"
  landed as the alternates line (only when detection is ambiguous).
- Gates: `python -m pytest` — 122 passed ×2.
