# Table Companion — Architecture & Design Record

**Status:** planning only. No code exists yet; nothing here is committed to as a
project. This document is the record of the 2026-09-25 architecture discussion
so that no ground has to be retreaded if/when development starts.

**Verdict in one line:** build the ICRPG table companion as a **separate,
standalone sibling project** (not in this repo), connected to the studio by
**two file artifacts** (a session manifest in, a session report out) — no
shared runtime, no shared code, no shared database.

**As-of note:** all file/line pointers into this repo were verified against
commit `7006a40` (2026-09-25). Re-verify before relying on them.

---

## Table of contents

1. [Context: what exists today](#1-context-what-exists-today)
2. [The core architectural thesis](#2-the-core-architectural-thesis)
3. [Components](#3-components)
4. [The seam: two file contracts](#4-the-seam-two-file-contracts)
5. [Draft schema sketches (v0.1)](#5-draft-schema-sketches-v01)
6. [Sync model](#6-sync-model)
7. [Stack recommendations](#7-stack-recommendations)
8. [Phasing and scope discipline](#8-phasing-and-scope-discipline)
9. [The standalone-vs-integrated deliberation (full record)](#9-the-standalone-vs-integrated-deliberation-full-record)
10. [Gotchas and environment risks](#10-gotchas-and-environment-risks)
11. [ICRPG mechanics mapping](#11-icrpg-mechanics-mapping)
12. [Relationship to the studio-side ICRPG tiers](#12-relationship-to-the-studio-side-icrpg-tiers)
13. [Data needed from the DM before building](#13-data-needed-from-the-dm-before-building)
14. [Decision log](#14-decision-log)

---

## 1. Context: what exists today

The current repo (`Documents/D&D`) contains a campaign world-simulation system:

- **`agentic-simulator/`** — a Python simulation engine. Factions act week by
  week; an LLM writes chronicles; a mechanical ledger (`events`) and rumor
  propagation (`rumors`) ground everything. Goals have week-deadlines and a
  "living goals" review proposes ledger-grounded goal updates.
- **`studio/`** — a FastAPI web studio (default port 8765) over the campaigns:
  lore vault (Obsidian-style `lore/entities/*.md` pages with wiki-links),
  maps pipeline (FMG worldmaps, city maps, site maps, UVTT battlemap exports,
  PNG scene rendering via `render-scene-png.mjs` + sharp), briefing packets,
  party knowledge disclosure, proposal/review/publish machinery for canon
  writes, and bounded single-pass LLM features.
- **`dnd-mapping/`** — the Node map tier (Fantasy Map Generator, settlemaker).

Facts about the data model that this design leans on (see §15 for pointers):

- Campaign state (`campaigns/<name>/simulation/state.yaml`) has top-level
  sections `meta`, `city`, `factions`, `events`, `rumors`, plus studio-compiled
  `knowledge`. **There is no player-character concept anywhere** — the sim is
  faction-vs-faction. The only party artifact is the party-disclosure record
  (`simulation/party-knowledge.yaml`).
- `campaign.yaml` has exactly `name`, `title`, `created`, `engines{...}`.
  There is no notion of a rules system anywhere; everything is deliberately
  setting- and system-agnostic. The only baked-in "rules" vocabulary is the
  faction resource enum (`coin | muscle | legitimacy`).
- Canon writes go through **proposals**: bundle = `proposal.yaml` manifest +
  `artifacts/` (state, chronicle, timeline entries, replay, diff). Exactly one
  pending proposal per campaign; accept goes through revision-checked
  publication with audit events and effect-id dedup. Two proposal kinds are
  state-only: `session_effects` and `goal_updates`.
- Session effects support exactly two mechanical effect types — `set_resource`
  and `set_field` (faction-scoped allowlists) — plus plain history events
  (`{actor, text}`, no mechanical effect). There is **no generic
  "append note" effect**, and `lore/timeline.yaml` entries are fed only from
  week acceptance and pending-lore approval.
- Player disclosure is a deliberate, per-fact step: `reveal()`/`revoke()` move
  public-only knowledge facts into `party-knowledge.yaml`; the player handout
  exports only revealed fact text. **This machinery is the conceptual model
  for the table companion's secrecy flag** (§4.1).

## 2. The core architectural thesis

The studio is a **canon brain**: single-writer, transactional, review-gated,
deliberately slow-moving. An at-the-table companion is a different animal:
**multi-device, real-time, ephemeral**. Two conclusions follow:

1. **Do not rebuild the campaign app for ICRPG.** The sim/studio stays the
   system-agnostic canon core. ICRPG-specific behavior belongs in a layer
   around it, not in it.
2. **Do not force phones into the studio either.** Bolting a WebSocket hub and
   real-time session state onto the studio would drag the canon brain into the
   exact runtime coupling the design exists to avoid, and the studio's
   trust model (nothing writes canon without DM review) must not be diluted.

Therefore: a **third, small sibling project** — the "table companion" — with
the studio connected by two file artifacts exchanged at session boundaries.
The table app never writes canon; the DM still reviews everything that flows
back. Zero change to the sim's trust model.

## 3. Components

### 3.1 Table server (tiny)

- FastAPI (or equivalent) with a **WebSocket hub**; single process.
- Session state lives **in memory** with a JSON snapshot per session, because
  table state is ephemeral by design (a session is one sitting; snapshots
  exist to survive a crash, not to be canon).
- A **room code** gates joins. Phones reach it over LAN.
- Serves the built player/GM client as static files.

### 3.2 Player client (PWA, not an app-store app)

- Phones scan a **QR code** encoding the LAN URL + room code, join the room,
  and get a home-screen icon ("Add to Home Screen" — no store, no install
  friction).
- Each player sees:
  - **their character card** — hearts (ICRPG HP), inventory as item cards;
  - the **shared loot pool** with a claim flow (the killer feature);
  - the always-visible **timer** (room timer / alarm clock);
  - a **dice feed** (later phase).
- Big, readable, card-based UI. This client is where most of the real
  development effort lives.

### 3.3 GM console

- Just another page, used on the laptop: timers, the TARGET/TN card, drag
  loot to players, adjust hearts, reveal NPC cards, (later) push a map image
  to screens.
- Runs in a browser tab alongside the studio (which stays open for canon/
  vault lookups — two tabs is a feature, not a compromise; see §9.2).

## 4. The seam: two file contracts

The entire decoupling rests on two versioned artifacts. Either side can
evolve independently; no shared runtime, code, or database.

### 4.1 Inbound: `session-manifest` (studio → table app)

One JSON/YAML artifact exported by the studio at session start, derived from
the prep material:

- scene/place, player-visible **NPC statblocks**, **loot candidates**,
- **timers pre-seeded from goal week-deadlines** (the sim's deadline'd goals
  are already ICRPG-style campaign timers — render them as such),
- one or two **map images** (phone-resolution PNG renders; the studio already
  has the rendering machinery),
- **party roster** (PC pages from the vault).

**Secrecy invariant:** every item carries a `visible_to_players` flag, and the
default is deny. The exporter must never include `faction.secret`,
`faction.knows`, or any non-revealed knowledge fact. This is the digital
analog of the studio's existing reveal/revoke disclosure machinery.

Before the manifest exists (v0), the GM console must support full manual entry
so the table app is usable standalone from day one.

### 4.2 Outbound: `session-report` (table app → studio)

Exported at session end:

- loot actually claimed (who got what) and any ad-hoc items created at the
  table,
- milestones awarded (ICRPG advancement) with reasons,
- notable events / session summary (DM-dictated or assembled from the log),
- optionally DM-curated timeline entries.

**Ingestion into canon:** the studio imports the report and **stages a
`session_effects` proposal** (history events, timeline entries) through the
existing review/accept flow. The table app never writes canon directly; the
DM reviews everything. Loot claims' canonical home (PC page edits vs. history
events only) is an open question (§14).

## 5. Draft schema sketches (v0.1)

Sketches only — to be firmed up into versioned **JSON Schemas** living in the
table-companion repo, consumed by the studio's exporter, with round-trip
tests on both sides (see §9.1, contract drift).

```yaml
# session-manifest/v0.1
schema: session-manifest/v0.1
generated: 2026-09-25T19:00:00        # studio export timestamp
campaign: sable-ford
session:
  title: "The Causeway Camp"
  place_ref: "[[The Causeway Camp]]"  # vault wiki-link, for GM context
targets:                               # the TN card on every screen
  default: 12
  scene: 14
timers:
  - id: t1
    label: "Ford garrison response"
    kind: global                       # room | alarm | global
    rounds: 4                          # or duration_s for real-time timers
    seeded_from: goal/FordMilitia/deadline   # provenance, for GM context
party:
  - pc_id: vex
    name: "Vex"
    player_label: "Sam"                # optional; device binding happens at join
    hearts: 2
    visible_to_players: true
npcs:                                  # ONLY player-visible ones unless flagged
  - npc_id: camp-sergeant
    name: "Sergeant Orla"
    statblock:
      hearts: 1
      effort_die: d6
      abilities: ["Shield wall", "Whistle for reinforcements"]
    visible_to_players: false          # DM-only card until revealed live
loot_pool:
  - item_id: l1
    name: "Ford signet ring"
    tier: uncommon
    bonus: "+1 CHA"
    description: "Warm to the touch."
    visible_to_players: true
maps:
  - map_id: m1
    label: "The causeway"
    image: "maps/causeway-phone.png"   # phone-resolution render
    source: site                       # site | city
    uvtt_ref: null                     # never parsed client-side in v0–v2
```

```yaml
# session-report/v0.1
schema: session-report/v0.1
campaign: sable-ford
session_id: 2026-09-26-causeway
played_on: 2026-09-26
loot_claimed:
  - item_id: l1
    pc_id: vex
loot_created:                          # ad-hoc items minted at the table
  - name: "Cracked shield"
    tier: common
    pc_id: brann
milestones:
  - pc_id: vex
    reason: "Held the causeway alone"
notable_events:                        # -> history events
  - actor: "Vex"
    text: "Talked the sergeant into an escort"
session_summary: "Free text, DM-dictated."
timeline_entries:                      # optional, DM-curated
  - when: "Week 2"
    title: "The Causeway parley"
    text: "..."
```

## 6. Sync model

Session state is a few KB, so the **simplest correct approach wins**:

- **Server-authoritative; broadcast full state on change.** No CRDTs, no
  WebRTC, no P2P, no offline merge — one room, one server, done.
- **Timers** carry a server-stamped `started_at` + duration; clients render
  the countdown locally from the broadcast (no tick spam), and the **server**
  resolves expiry so there is one authoritative alarm.
- **Reconnect = full resync.** Version counter on state lets a reconnecting
  client detect staleness.
- **Device identity:** a per-device token in `localStorage`; closing the tab
  and rejoining must restore the same seat.
- **Persistence:** JSON snapshot per session, restorable; sessions themselves
  are ephemeral.
- **GM approval** of joins (room code + approve) keeps randos off even on a
  shared network.

## 7. Stack recommendations

- **Server:** Python + FastAPI + websockets (uvicorn, single process),
  consistent with the existing studio and the author's fluency. The seam is
  files, so server language carries no type-sharing penalty. Python and Node
  are both already in the portable-bundle runtime story, so no new runtime.
- **Client:** Vite + **React or Svelte** (open decision, §14), TypeScript
  recommended, PWA manifest. Ship built static assets from the server; the
  build step is dev-time only.
- **No service worker in v0** — LAN HTTP can't register one anyway (see
  §10). Add later with mkcert/self-signed if offline is ever wanted.
- Full-stack TypeScript (shared types) was considered and rejected: the
  seam is schema-enforced files, not shared types, and Python consistency
  with the existing toolchain wins.

## 8. Phasing and scope discipline

- **v0 — the magic.** Server + WS hub, QR join with GM approval, GM console,
  player character card (hearts, inventory), **loot pool with claim
  animation**, one room timer + alarm clock, snapshot persistence. Full
  manual entry — **zero studio dependency**. (Roughly a weekend or three.)
- **v1.** Effort dice roller with a shared roll feed, milestone buttons,
  NPC-card reveal, GM console polish.
- **v1.5 — the seam.** Studio exports `session-manifest` (from prep/briefing
  + PC pages); table server imports it. Table app exports `session-report`;
  studio ingests it into a `session_effects` proposal. Note: the studio-side
  ingestion work happens in the D&D repo regardless of where the table app
  lives.
- **v2 — maybe.** Map image sharing to screens, initiative order, and the
  one genuinely-cool loose-coupling nicety: a **live-reveal push** (studio →
  table server webhook) so pressing "reveal" in the studio can drop a handout
  on players' phones. Five endpoints if ever built; explicitly optional.
- **Explicitly never:** fog of war / token drag (the VTT tar pit — the tool
  already makes battlemaps; it must not become Roll20), remote/online play,
  CRDT or offline merge, app-store native builds, LLM calls at the table
  (latency is hostile mid-session; LLM work belongs in prep, in the studio).

## 9. The standalone-vs-integrated deliberation (full record)

Recorded so this is never re-argued from scratch.

### 9.1 Honest cons of going standalone (and mitigations)

1. **Contract drift.** The manifest/report schemas are a cross-repo contract
   with no compiler enforcing them. *Mitigation:* versioned JSON Schemas in
   the table-companion repo, consumed by the studio exporter; round-trip
   tests on both sides.
2. **Two things to launch at the table.** *Mitigation:* orchestration, not
   integration — one launch script; later a "start table session" button in
   the studio that **spawns** the sibling server. Spawning a process is loose
   coupling; merging code is not the fix.
3. **Seam-sprint friction.** During v1.5 the work bounces between repos.
   One-time cost during that sprint only.
4. **Studio work happens regardless.** Report ingestion into `session_effects`
   is D&D-repo work no matter what. Standalone just makes it schema-shaped
   rather than runtime-shaped.
5. (Minor) duplicate deploy scaffolding; the table app needs a way to locate
   the campaign folder (drag-drop the manifest; no live path coupling).

None of these rises to "keep it integrated."

### 9.2 Integration candidates assessed (why each dissolves)

- **Maps — the strongest pull, and it dissolves.** The D&D repo owns the
  whole map pipeline, but what the table app needs is *images at session
  start*, which the manifest carries. The only thing integration would add
  is live fog-of-war reveal from UVTT data — a VTT feature, client-side work
  and a tar pit regardless of repo layout. Do export **phone-resolution PNG
  renders** in the manifest (the render machinery exists); that is a manifest
  detail, not a coupling reason.
- **Mid-session vault lookups.** The DM has the studio open in a laptop tab
  already. Two tabs cost nothing — and vault content should never reach
  player phones anyway (secrets).
- **Live reveal to players.** Genuinely cool; the clean version is the
  optional v2 webhook push (studio → table server), not shared code.
- **Mid-session canon writes.** Would require the table app to write canon,
  breaking the review-gated trust model. The session-report → proposal flow
  exists precisely so this happens at session end, reviewed.
- **Shared LLM plumbing.** No pull: no LLM at the table; prep-time LLM stays
  in the studio.
- **Single-port convenience.** Adding a WS hub + real-time state to the
  studio is exactly the coupling being avoided; not worth one command saved.

### 9.3 Middle ground considered and rejected

A third **package inside this repo** (`table/` alongside `agentic-simulator/`
and `studio/` — the repo is already multi-package): one clone, separate
runtime/tests. Its only real advantage is seam-sprint convenience. Its cost
is philosophical and practical: ICRPG-specific code living beside a
deliberately system-agnostic canon core, and a bigger repo wrapped around
careful transactional machinery. **Rejected.** Separate repo, sibling folder
in the same workspace; the portable-bundle deploy plan (one zip, sibling
layout) ships both from a single artifact when the time comes.

## 10. Gotchas and environment risks

- **Guest-WiFi client isolation** will silently block phones → laptop. Test
  the actual venue network early. **Windows Mobile Hotspot** makes the laptop
  its own network (self-contained game network) — the reliable fallback.
- **PWA/service-worker HTTPS requirement:** secure context is required for
  service workers *except* localhost. Over LAN HTTP, "Add to Home Screen"
  still works but offline mode won't register. Acceptable for v0; mkcert or
  a self-signed cert + one-time trust is the later path if wanted.
- **iOS Safari quirks:** audio autoplay policies, no install prompt (manual
  A2HS), wake-lock behavior. Use the **Screen Wake Lock API** for the timer
  screen and the GM console so phone sleep doesn't kill the clock view.
- **QR must encode the LAN IP**, not `localhost`; hostname/mDNS discovery is
  a nice-to-have, hardcoding-the-IP-at-boot is fine for v0.
- **Never trust client clocks** for timer authority (server `started_at`).
- **Player-device privacy:** the manifest's default-deny visibility flag is
  the only thing standing between faction secrets and the players' phones —
  test the exporter against a campaign with live secrets before first real
  use.
- **Security stance: the trusted LAN is the outer gate** (ruled 2026-10-06).
  The room code — including the unauthenticated `/api/bootstrap` copy of it —
  is a convenience, not a secret; the GM's knock-approval is the real
  boundary. Anyone on the network can knock with any name regardless, so
  hiding the code adds friction without adding a boundary. If the venue
  threat model ever changes (semi-public Wi-Fi), the escape hatch is gating
  the bootstrap room code behind the GM key.

## 11. ICRPG mechanics mapping

What the app is actually representing (terminology varies by edition — see
§13; ICRPG = Index Card RPG, Runehammer):

| ICRPG concept | Digital representation |
| --- | --- |
| Hearts (10 HP each; mooks take partial hearts) | Heart display on character/NPC cards; GM tap-to-damage |
| TARGET numbers (e.g. 12/14/16/18 ladder) | The TN card, mirrored on every screen |
| Effort dice (d4/d6/d8/d10/d12 by effort type) | Dice roller with effort visualization; accumulated-effort counters |
| Timers / alarm clocks (the signature tension device) | Server-authoritative countdowns; goal-deadline seeds from the manifest |
| Loot tiers + item cards | Item-card UI; loot pool → claim flow; card art/flavor later |
| Milestones (advancement, not XP) | GM console milestone buttons → session-report |
| Index cards on the table | The whole client is, deliberately, index cards on phones |

Design stance: the app digitizes the **state**, not the rules. It does not
need to know how effort is computed — the GM taps, the app records. Rules
primers live as vault pages in the studio (§12), not as client logic.

## 12. Relationship to the studio-side ICRPG tiers

The earlier (same-day) ICRPG integration discussion produced tiers for the
*studio* side. They remain the plan, and the table companion **supersedes
Tier 3**:

- **Tier 0 — vault only, zero code, do first:** rules-primer pages
  (`kind: rules`) written as the table's *personal* conventions (never book
  table reproduction — copyright hygiene; personal summaries in campaign
  data are fine), plus PC/recurring-NPC entity pages (`kind: pc` / `kind: npc`).
  These ground all later features: chronicle grounding, missing-pages drafts,
  and eventually the manifest's party roster + statblocks.
- **Tier 1 — ICRPG prep packet (small code):** a `system: icrpg` field in
  `campaign.yaml` gating a prep section in the briefing: TN card,
  goal-deadlines-as-timers, expected opposition statblocks, loot candidates.
  Deterministic render first; optionally one bounded LLM pass following the
  `goals.py` pattern (grounded window → YAML → validate → findings). Prep is
  DM-facing and non-canon: render with findings, **no** proposal machinery.
  This packet is the natural source of the `session-manifest` in v1.5.
- **Tier 2 — award tracking:** milestone/loot awards recorded as plain
  history events and/or timeline entries (no new effect types initially).
  The table companion's session-report feeds exactly this flow.
- **Tier 3 — tracker page in the studio: superseded.** What would have been a
  studio-resident tracker is now the table companion; do not build Tier 3
  in the studio.
- **Chronicle dialect:** week chronicles should stay mechanics-agnostic;
  ICRPG vocabulary (hearts, effort, TNs) belongs in prep and at the table,
  not in canon prose.

## 13. Data needed from the DM before building

Roughly in order; items 1–4 unblock Tier 0 vault work even before any table
app exists.

1. **Edition and modules** — ICRPG Master Edition? Core 2e? Any settings
   (Alfheim, Warp Shell)? Terminology differs slightly.
2. **What the table actually uses** — stat list, the TN ladder as run, effort
   dice per tier, heart/HP conventions for mooks vs. bosses, classless vs.
   classes, magic handling.
3. **House rules** — dictation is fine; these become the `kind: rules` pages.
4. **PC roster** — names, origins, stats, hearts, current loot/abilities;
   index-card text is fine, it gets turned into vault pages.
5. **Loot source** — book tables (summarized) vs. homebrew; regional flavor
   (per-faction/per-place grounding is a natural sim fit).
6. **Milestone cadence** — how many milestones per level and what they grant.
7. **Build decisions** — confirm v0 scope; choose SPA framework; name the
   project/repo.

## 14. Decision log

**Decided (with rationale):**

| Decision | Rationale |
| --- | --- |
| Standalone sibling project, outside this repo | Canon brain vs. ephemeral table state; protect the studio's trust model and system-agnostic core (§2, §9) |
| File-artifact seam: `session-manifest` in, `session-report` out | Session-boundary handoffs cover every real integration need; either side evolves freely (§4, §9.2) |
| Session-report → `session_effects` proposal via existing review flow | Table app never writes canon; DM reviews everything (§4.2) |
| Server-authoritative, full-state broadcast; no CRDT/P2P/WebRTC | State is KBs; simplest correct approach (§6) |
| PWA, not native app | Zero distribution friction; QR + A2HS is the whole install story (§3.2) |
| Python/FastAPI server | Consistency with existing toolchain; seam is files so no type-sharing penalty (§7) |
| Manual entry in v0, studio dependency only in v1.5 | Table app usable and testable standalone from day one (§8) |
| Never-list: no fog of war/tokens, no remote play, no offline merge, no native builds, no table-side LLM | VTT tar pit + scope protection (§8) |
| Manifest default-deny `visible_to_players`; exporter never emits secrets | Digital analog of the studio's reveal/revoke machinery (§4.1, §10) |
| Middle-ground "third package in this repo" rejected | Seam-sprint convenience doesn't buy back the philosophical/practical cost (§9.3) |
| Studio-side ICRPG Tier 3 (tracker) superseded by this project | Avoid building the same thing twice (§12) |

**Open:**

| Question | Notes |
| --- | --- |
| SPA framework: React vs. Svelte | Pick one and go; client is the bulk of the effort (§7) |
| Project/repo name | "table-companion" is a placeholder |
| v0 scope sign-off | §8 v0 list is the proposal |
| Canonical home of loot claims | PC vault-page edits vs. history-events-only (§4.2) |
| HTTPS/offline path | Deferred; A2HS-only is fine for v0 (§10) |
| Live-reveal push (studio → table) | v2-maybe webhook, explicitly optional (§8, §9.2) |
| Map sharing scope | v2-maybe; static images only, UVTT fog explicitly out (§8, §9.2) |
| Real-time vs. round-based timer semantics | Both ICRPG kinds exist (room timers in rounds, alarms in real time); v0 should probably do both but the alarm UX is undecided |

## 15. Repo file pointers (as of `7006a40`, 2026-09-25)

Verified during the design session; re-verify before relying on them.

- State schema/validation: `agentic-simulator/src/store.py:19-54`
- Effect types & application: `agentic-simulator/src/effects.py:35-63,122-176,189-238`
- Faction resource enum: `agentic-simulator/src/effects.py:60-63`, `agentic-simulator/src/llm.py:35-36`
- Bounded single-pass LLM pattern: `agentic-simulator/src/goals.py` (LEDGER_WINDOW=40, RUMOR_WINDOW=20)
- Campaign manifest writer: `studio/spine.py:163-204`; state load: `studio/spine.py:572-574`
- Entity page parser: `studio/spine.py:342-371`
- Link index (entity/chronicle/map sources): `studio/links.py:121-197`, collision findings `studio/links.py:260-280`
- Briefing build/render: `studio/briefing.py:73-157,160-189`
- Party disclosure & handout: `studio/briefing.py:30,212-268` (DISCLOSURE_FILE = `simulation/party-knowledge.yaml`)
- Proposal kinds & bundles: `studio/proposals.py:78`; state-only kinds `studio/routers/simulation.py:56`
- Session-effects proposal staging: `studio/routers/simulation.py:974-993`
- Goal-updates → set_field conversion: `studio/routers/simulation.py:1117-1124`
- Timeline ownership: `studio/timeline.py:62-100`
- Knowledge compilation: `studio/knowledge.py:207-218`
- Map rendering (phone-res PNGs for the manifest): `dnd-mapping` render-scene-png.mjs (sharp)
