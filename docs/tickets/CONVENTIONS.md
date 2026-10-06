# Ticket conventions

How tickets in this directory work — for whoever writes one (usually an
agent). The copy-paste template is at the bottom; the rules come first
because they are the part that isn't obvious from the skeleton.

## What a ticket is

A ticket is the durable record of one finding from real use. Reviews of
real use (a table session, a code review, a GUI QA pass, a user request)
are converted into tickets, and then the review documents themselves are
deleted — the tickets are the record. The precedent here is the
2026-10-02 full review, whose findings are tickets 32 and 33. Two
consequences:

- A ticket must be **self-contained**: it carries its own evidence and
  must never dangle a pointer at a deleted review doc.
- Completed tickets are **never deleted**. `archive/` is the history;
  only a ticket's status line and location change over its life.

## Rules

- **Numbering:** sequential two-digit number (`34-…`), never reused;
  gaps are fine. The number is the cross-reference id — later tickets
  cite each other by number. This repo's sequence starts at the imported
  32/33 (the dnd-campaign-generator review of table-companion before the
  split). The dnd repo numbers its own tickets independently and already
  has 34+, so when citing a dnd-repo ticket, write "dnd repo #NN", never
  a bare `#NN`.
- **One ticket = one lane:** sized so one agent can implement and merge
  it independently in one sitting. Group findings by module/fix
  coherence, not by the order the review found them.
- **Acceptance criteria are test-nameable.** Each criterion names the
  test that pins it (or is a directly checkable claim). "Works better"
  is not a criterion. The client has no test suite — a client criterion
  is pinned by the `npm run build` typecheck gate or by a named manual
  click-through (see WORKFLOW.md).
- **User rulings live in the ticket**, under `## Ruling (do not revisit)`
  or `## Decisions baked in`. A ruled-out approach is not re-proposed in
  a later ticket. Repo-level scope rulings (no fog of war, no remote
  play, no LLM at the table, …) live in DESIGN.md §8 and §14 — a ticket
  cites those rather than restating them.
- **Deviations are documented, not silent.** When an implementation lands
  differently than proposed, the ticket's Implementation notes say so and
  why.
- **Status lifecycle:** `proposed` → `in-progress` → `completed`,
  `superseded`, or `abandoned`. "Parked" is not a status — write
  `proposed` with a parked note (as 32 and 33 do). Flipping to one of
  the last three means the file moves to `archive/` in the same change.
- **No index.** There is deliberately no README or table listing the
  tickets; the status line in each file is the record.

## Template

Copy for a new ticket. The bold fields: `Status` (always, exactly one of
the five statuses), `Priority` (P1/P2/P3 or a short phrase), `Area`
(files/modules the work touches), `Found by` (what surfaced it, with
date). The three spine sections are Problem / Proposal / Acceptance
criteria; Implementation notes are added when the work lands, not up
front.

```markdown
# NN — Title in a few words

**Status:** proposed
**Priority:** P1 | P2 | P3 (or a short phrase)
**Area:** `files/modules/` the work touches
**Found by:** what surfaced it + date

## Problem

What is wrong today, with evidence: observed behavior, file:line,
reproduction. Ground it — this section must still make sense after the
review that produced it is deleted.

## Proposal

The concrete change. Enough detail that an agent can implement it
without re-deriving the design; call out anything that needs a user
ruling rather than deciding it silently.

## Acceptance criteria

- [ ] criterion — pinned by `tests/test_ws_flow.py::test_bar`
- [ ] criterion — pinned by `npm run build` + manual click-through of
      the join flow

## Implementation notes (YYYY-MM-DD)

How it actually landed: commit refs, deliberate deviations from the
proposal, follow-ups. Written when the status flips.
```

In-place examples: 32 (findings grouped by fix coherence rather than
review order) and 33 (a parked status line, nameable acceptance
criteria). `archive/` will accumulate completed examples as work lands.
