# Table Companion

Hearts, timers, and loot for the ICRPG table. A tiny LAN server plus a
phone-first client: the GM runs a console on the laptop, players scan a QR
code and sit down at index cards on their phones. No accounts, no install,
no internet needed.

**Status: v0 works end to end** — GM console, QR join with GM approval, player
character cards, server-authoritative timers (alarm clocks + room timers), a
shared loot pool with a claim flow, and snapshot persistence. The studio seam
(`session-manifest` in, `session-report` out) is v1.5; the GM console already
downloads a `session-report/v0.1`-shaped JSON. Design record: [DESIGN.md](DESIGN.md).

**Currently deprioritized** — possibly to be resumed later

## Run it

```
pip install -e .            # or: uv sync
python run.py               # serves on 0.0.0.0:8770
```

The banner prints everything:

- **GM console** — open `http://localhost:8770`, paste the GM key (once; the
  browser remembers it)
- **Players** — click **Show QR** and point phones at it, or type the printed
  `/join?room=CODE` URL; every join needs GM approval

`--fresh` starts a new session (discards the last snapshot). Without it, the
previous session is restored — room code, GM key, hearts, timers, loot — so a
crash mid-session costs nothing.

Keep this window open while you play. **Ctrl+C stops the server.**

### At the venue

- The QR encodes the server's LAN IP, detected at boot. If phones can't reach
  it (guest-WiFi client isolation is the usual suspect), **Windows Mobile
  Hotspot** makes the laptop its own network and always works.
- "Add to Home Screen" works over LAN HTTP (no service worker offline mode —
  fine, the server is on the table anyway).
- Player data lives on the server (snapshot in `data/`); the phone mirrors it
  and keeps a device token, so a reload restores the seat and a lost phone is
  fixed by the GM re-seating the same character on the new device.

## Layout

```
run.py               launcher: banner, uvicorn, snapshot restore
server/
  state.py           state model, role-filtered views, snapshot persistence
  actions.py         the whole action vocabulary (GM + player), role-gated
  hub.py             Room: connections, seat refresh, broadcast
  app.py             FastAPI: /ws hub, /api/bootstrap, static client
  content.py         starter content packs (content/*.json)
client/              Vite + React + TS PWA (built assets served by the server)
content/alfheim.json original-flavor starter kit (loot + timers + TN defaults)
scripts/make_icons.py pure-stdlib PNG icon generator (run once, output committed)
```

## Docs

`DESIGN.md` is the design record. Process lives in `docs/`:
`docs/WORKFLOW.md` (implement → verify → review → merge, severity
definitions) and `docs/tickets/CONVENTIONS.md` (ticket format, template,
archive lifecycle — open tickets: 32–52). `AGENTS.md` carries the
repo-wide agent rules.

## Develop

Client (from `client/`): `npm run build`. Two machine quirks are already
handled: `client/.npmrc` routes npm scripts through Git Bash (cmd.exe
mis-parses a literal `&` in the working path — this repo originally lived
under `Documents\D&D`; the .npmrc is harmless elsewhere), and the
nodist npm shim needs its global npm pinned once via `nodist npm 10.2.3`
(done 2026-09-26). For live-reload dev: `npm run dev` (vite proxies `/api`
and `/ws` to :8770) and run the python server alongside. Python edits need a
server restart; static/built assets reload.

Tests: `python -m pytest` — the WebSocket tests boot a real loopback server
and speak actual WebSocket (this starlette/anyio combo has a broken
TestClient WS session; shared site-packages must not be upgraded under the
studio).

## Deliberately not here (see DESIGN.md §8)

No fog of war or token drag, no remote play, no offline merge, no app-store
builds, no LLM at the table. The app digitizes the **state**, not the rules.
