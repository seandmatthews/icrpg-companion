# Workflow — implement, verify, review, merge

The loop one ticket goes through from `proposed` to `completed`. The
ticket's format lives in `docs/tickets/CONVENTIONS.md`; repo-wide rules
are in `AGENTS.md`. This file records the part those don't: what "done"
means, how verification actually runs, and the rules a review and a
merge obey.

## Definition of done (for a ticket)

- Every acceptance criterion is demonstrably true, and each box is
  ticked only after it was verified. The criteria name the tests that
  pin them — new behavior lands with its pinning tests in the same
  change. A change with no test for a named criterion is not done.
- `python -m pytest` is green for the whole suite, not just the touched
  file — it is one suite and every test speaks to a real loopback
  server, so there is no faster tier to hide behind.
- Client changes: `npm run build` is green (`tsc --noEmit` is the only
  automated client gate) **plus** one manual click-through of the
  changed flow — boot the server, do the thing, look at it. Console
  flows are checkable in a desktop browser; the phone-specific flows
  (QR join) at least get the join URL exercised.
- The ticket's Implementation notes are written: commit refs, and every
  deviation from the proposal with the reason. Silent deviations are
  how drift compounds.
- The status is flipped and the file moved to `docs/tickets/archive/`
  in the same change (CONVENTIONS.md).
- If behavior or copy drifted from any doc, the doc is updated in the
  same change. The README's Layout/Develop sections and DESIGN.md
  describe reality — they move with the code, never one ahead of the
  other.

## Running the tests

    python -m pytest          # the whole suite — real WS server, ~seconds

Traps and notes:

- The WebSocket tests boot a real uvicorn on port 0 and speak actual
  WebSocket: this starlette/anyio combo has a broken TestClient WS
  session, and the shared site-packages must not be upgraded to "fix"
  it (the studio shares that environment).
- Python edits need a server restart to take effect; static and built
  client assets reload.
- Client build quirks are machine-level and already handled (see README
  → Develop): `client/.npmrc` routes npm scripts through Git Bash, and
  the nodist npm shim is pinned once.
- There is deliberately no lint config and no CI. The gates are pytest
  and the tsc build; if that changes, this file changes with it.

## Review rules

- The reviewer reports findings; it does not fix them in the same pass.
- Every finding gets one of: a ticket, or an explicit already-fixed /
  won't-fix disposition. Findings are never silently dropped — and a
  review whose findings all turn out to be already fixed is deleted
  without tickets.
- After conversion, the review document itself is deleted — the tickets
  are the record (2026-10-02 ruling, inherited with tickets 32/33).
  This is why a ticket must be self-contained.
- Severity, used by tickets and reviews alike:
  - **P1 — silent wrongness.** Corrupts state or bypasses a guardrail
    with nothing the user can see: a snapshot that loses work, a silent
    gate bypass, a write that lands somewhere wrong.
  - **P2 — loud wrongness or dishonesty.** The user can see or hit it:
    wrong output, a missing disclosure, a readable crash, a robustness
    hole on hostile input, a dead timer-watcher.
  - **P3 — polish.** Consistency, docs and copy, minor robustness,
    hygiene.
- The standing review lens — what past reviews actually caught, so
  start there: malformed and hostile input shapes (WS frames, content
  packs), lock and flag interleavings (TOCTOU), crash windows mid-write
  (snapshot persistence), frontend affordances that fail silently, and
  honesty gaps between what the UI claims and what the state shows.

## Merge discipline

- One lane (branch or worktree) per ticket, independent and mergeable on
  its own — tickets are sized for this by CONVENTIONS.md.
- Merge only with the suite green on the lane (plus the client gate when
  the lane touches `client/`).
- A red merge is reverted immediately and re-landed fixed — revert
  first, investigate after.
- No ride-along changes. If something rides along anyway, it is named
  in the commit message.
- The commit that lands the work carries the ticket's status flip and
  archive move with it.
