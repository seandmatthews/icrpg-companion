# AGENTS.md

Repo-wide working rules for agents. The design record is `DESIGN.md`; the
user-facing README is `README.md`.

## Tickets: status lines & archive

Tickets live in `docs/tickets/` (finished ones in `docs/tickets/archive/`).
Every ticket starts with one status line, `**Status:**` followed by exactly
one of: `proposed`, `in-progress`, `superseded`, `completed`, `abandoned`
(plus a short note — dates, commit refs). When a ticket's status becomes
`superseded`, `completed`, or `abandoned`, move it into
`docs/tickets/archive/` in the same change; `proposed` and `in-progress`
tickets stay in `docs/tickets/`. There is no tickets index — the status
line in each file is the record. Format, numbering, and the rest of the
conventions (with the template): `docs/tickets/CONVENTIONS.md`. The
implement → verify → review → merge loop, the verification rules, and the
severity definitions: `docs/WORKFLOW.md`.

## Kill dev processes when work concludes

Before ending a session, STOP every dev process you started or found running:
the table server (`python run.py`, default port 8770) and any vite dev
server (`npm run dev` in `client/`, default port 5173).
A server left running keeps serving STALE Python code after your edits
(static and built JS reload, Python does not), squats the port, and
inherits into the next session as a confusing pre-existing process.

- Find listeners: `netstat -ano | grep LISTENING | grep -E ":(8770|5173)"`
- Kill the tree (Git Bash): `taskkill //F //T //PID <pid>` — `//T` so child
  processes (reload workers, node watchers) die with it
- Verify before signing off: re-run the netstat check — the ports must be free.
