# EnvelOps — Roadmap & Current Status

> Living "what's next" document. [`REQUIREMENTS.md`](REQUIREMENTS.md)
> (what/why) and [`ARCHITECTURE.md`](ARCHITECTURE.md) (how) are the stable
> references; this document tracks *where things stand* and *what's still
> open* — not a full history of how each item got built. Detailed
> session-by-session narrative (what was tried, what broke, how it was
> verified) is not kept here once an item ships; the Changelog below is a
> one-line-per-item pointer, not a write-up. Reusable engineering gotchas
> (not just "this one bug") live in `CLAUDE.md` instead, so they survive
> this kind of pruning.
>
> Housekeeping pass 2026-07-31: this file was ~1800 lines of full
> session write-ups. Condensed to open items + a compact changelog: same
> content class as `git log`, not a substitute for it — check `git log
> --merges` / `gh pr view <N>` for the real detail behind any entry below.

---

## Current state (as of 2026-08-03)

EnvelOps is a solo portfolio project demonstrating AI behavior
orchestration/safety/configuration — **not** a product being shipped to a
real business. The original pilot (a friend's honey business) is
deprioritized; see the Changelog's 2026-07-31 entries for the full
scope-pivot reasoning. Concretely, right now:

- **Telegram** is the one real channel integration. Instagram/WhatsApp/
  Facebook/Email are simulated (`app/channels/simulated_client.py`) — real
  pipeline, webhook-shaped entry points, no real platform contacted.
- Order-status/inventory lookup use **real** Gemini tool-calling over
  **fake**, deterministic connectors (`app/commerce/`) — not a real
  Shopify/WooCommerce integration.
- Turkish/bilingual pipeline support is cut, fully, including
  `escalation/safety_gate.py`'s own pattern lists. Frontend i18n UI chrome
  (`react-i18next`) is untouched and unrelated.
- Two calibration tenants are seeded (Wildroot Apparel Co, Voltage
  Gadgets), each run against ~28 real Bitext-sampled customer-support DMs
  via `scripts/seed_calibration_tenant.py` — the current primary way new
  tenant configs get exercised, replacing the original synthetic-then-
  real-pilot validation plan (REQUIREMENTS §12).
- The Dashboard page is real now (stats/trend/donut intent breakdown/
  channels table/knowledge status, all live tenant data) — no more open
  items carried in this file as of PR #46.
- Channels and Integrations are new nav pages. Integrations stays a
  static preview, no backend — real e-commerce connectors stay out of
  scope (ARCHITECTURE §12). Channels is now partly real: it lists the
  tenant's actual channels with a **working per-channel AI auto-reply
  on/off switch** (`GET /channels/connected`/`PATCH /channels/{id}`) —
  real channel *creation* is still script-only.
- All PRs through #47 are merged into `main`, plus the channel AI-toggle
  work described in the changelog below, not yet merged as of this
  writing (**check this**: verify the actual PR number/state with `gh pr
  list`/`gh pr view <N> --json state` rather than trusting this file).
  Always check `gh pr
  view <N> --json state` before trusting any specific PR's status — this
  file goes stale between sessions.

## Open items

Real, not yet designed in detail, not currently being worked:

- **Bug, found live 2026-08-03, not yet fixed** — a Celery worker process
  can only successfully complete its *first* `process_incoming_message`
  task after starting; every subsequent task in that same warm worker
  process fails with `RuntimeError: ... got Future ... attached to a
  different loop` (asyncpg). Root cause: `app/core/db.py`'s async
  `engine`/`async_session` are module-level singletons (created once,
  when the module is first imported into the worker process), but
  `pipeline/tasks.py`'s `process_incoming_message` wraps every task body
  in a fresh `asyncio.run(...)` call — each call spins up a *new* event
  loop and tears it down when done. The engine's connection pool holds a
  pooled asyncpg connection bound to the *first* call's event loop; the
  *second* call's new loop can't use it. Found by sending two real,
  separate webhook messages to the same real (non-test) channel a
  minute apart, with the worker left running in between — the first
  succeeded, the second failed outright (reply silently never sent; the
  inbound message itself is still stored, since that commit happens
  before the task is even dispatched). Restarting the worker between
  messages "fixes" it, which is itself confirmation of the cause, not a
  workaround to rely on. **Not yet designed**: likely fix direction is
  either creating the engine fresh per task (defeats connection pooling)
  or restructuring so the pool isn't torn down/recreated across
  `asyncio.run()` boundaries (e.g. one long-lived loop per worker process
  instead of one `asyncio.run()` per task) — needs its own look before
  picking, not a same-session guess. Same root-cause shape would affect
  `follow_up_check` too, though it's less likely to fire twice against a
  single warm worker in practice given its 30-minute cadence.
- **Minor, not urgent**: ~10–15s per Test Console send (up to several
  sequential Gemini calls, none parallelized — `search_knowledge` doesn't
  actually depend on `understand_intent`'s output, so parallelizing those
  two is a viable future latency win).
- **A "Markdown" knowledge-source type** — deliberately excluded from the
  knowledge-sources redesign (PR #43) since it isn't real backend
  capability yet; would need a small ingestion addition, not a redesign.

**Longer-horizon, deferred not cut** (REQUIREMENTS §10/§13 have the full
reasoning, not duplicated here since these are phase-level, not
session-level): graph-augmented retrieval for relationally-complex
domains, embedding/lead-scoring fine-tuning, multi-user roles beyond
"owner."

**Cancelled** (won't be revisited without re-opening the decision —
recorded so they don't get silently re-proposed): the template gallery
and AI copilot for setup/tuning/monitoring (both predicated on the
multi-vertical, many-tenant breadth the 2026-07-31 pivot walked back
from); real Instagram/WhatsApp/Facebook Messenger integrations and real
commerce connectors (Shopify/WooCommerce/etc. — simulated versions ship
instead); Turkish/bilingual pipeline support; `book_or_checkout` beyond a
static link (a real per-order checkout/booking connector); ROI/ad-spend
attribution and a multi-model prompt playground (cut early as scope
creep). **Added 2026-07-31, same pivot logic** — real-business-ops
concerns that don't add to what this project actually demonstrates:
human-paused conversations (a human replying directly outside the
pipeline — the conversation thread view's read-only state is now a
settled design choice, not a placeholder for this, see ARCHITECTURE
§10); channel failure behavior beyond the health-check stub; data
retention/deletion policy specifics; and whether/when general
draft-and-approve comes back (including draft-approval timeout/
notification mechanics, which only mattered if it did) — Phase 1's
auto-send + safety-floor-escalation-only gate (ARCHITECTURE §5) stays
final, not provisional.

## Changelog

**2026-07-28** — Conversation rail intent/lead-score badges; per-message
pipeline diagnostics in Test Console.

**2026-07-29** — Conversation history threading across the pipeline (PR
#25). Dev-only tenant switcher for local testing (PR #26). Knowledge
source + trigger-phrase delete (PR #27), later extended to view/edit for
manual sources (PRs #32–34). One clarifying question asked before
escalating on an ambiguous message, instead of an immediate escalation
(PR #29). Live rail/badge updates via SSE (PR #30). Natural escalation
cover reply + internal-note bubble in the conversation thread, plus a
guard against a second inbound message on an already-escalated
conversation (PR #31). Multi-tenant showcase seed script — 4 verticals,
each with a login-able demo user (`scripts/seed_showcase_tenants.py`).
`keep_chatting`'s knowledge-gap disclaimer turned into a real escalation
instead of a silent dead end, plus several other live-found
`keep_chatting` quality bugs fixed the same session (PRs #32–34,
`scripts/run_bitext_stress_test.py` added as part of this work). Two
pipeline bugs found and fixed via live Test Console use: a bare greeting
producing a nonsense disclaimer, and the hot+purchase-intent branch
silently pausing forever with no visible escalation when
`closing_action` is `escalate_to_human` (the default).

**2026-07-30** — Typed, bounded per-tenant AI behavior configuration
(`TenantBehaviorConfig`, `app/tenants/behavior_config.py`) replacing
hardcoded prose scattered across pipeline nodes (PR #35). Tenant settings
API + a two-column, tabbed Settings UI with independent per-tab save via
`PATCH /tenants/settings` (PR #36).

**2026-07-31 — portfolio scope pivot.** Direct instruction: the real
pilot is deprioritized, EnvelOps becomes a solo portfolio project. Turkish/
bilingual support cut; real Instagram/WhatsApp/Facebook/commerce
integrations cut in favor of simulated channels + real Gemini
tool-calling over fake deterministic connectors; tenant count capped at
~2 rather than growing across every vertical; template gallery and AI
copilot cut as predicated on the abandoned multi-vertical ambition (PR
#37). `escalation/safety_gate.py`'s own Turkish patterns removed too, for
full English-only consistency; two real calibration findings fixed
(a fabricated support-email workflow for order-modify/cancel requests,
and an order-modify request misrouted into `book_or_checkout`) (PR #38,
live-verified in PR #39). Safety-floor efficacy-cue gap closed — risk/
safety/complication language now trips the outcome-guarantee check, not
just functional-outcome words like "cures"/"works" (PR #40). UI polish:
conversation rail filter chips + pagination, Settings tab reorganization,
free-text fields converted to resizable textareas (PR #41). PDF knowledge
source support (PR #42). Knowledge sources page full redesign — stat
tiles, pill-style type selector, per-chunk preview, search/filter (PR
#43). Also this day: docs housekeeping — `ROADMAP.md` condensed from
~1800 lines of session write-ups to open items + this changelog (PR #45).

**2026-08-01 through 2026-08-03** — Real Dashboard page (`GET
/dashboard/summary` + stat tiles/trend chart/intent breakdown/channels
table/knowledge status), closing the last open item above, all one PR
(#46) iterated live against direct feedback:
- Hand-rolled SVG charts throughout, no new frontend dependency
  (`frontend/src/components/dashboard/`). First pass used a ranked bar
  list for "conversations by intent" after this app's status-color
  tokens failed a categorical CVD-separation check as a set; reversed to
  a real donut chart on direct request, with a dedicated palette instead
  (the dataviz skill's own reference palette for the three segments with
  no existing badge color, this app's real `--accent`/`--info` tokens
  reused for the two that do — re-validated for CVD separation in this
  exact mixed order before shipping).
- "Escalated" changed from a running total to *currently unresolved* —
  the total-count version didn't move when an escalation got resolved,
  which read as a bug next to two other now-facing tiles (Hot Leads,
  Avg Response Time).
- Recent Escalations card removed (direct request) after initially
  shipping it as a clickable deep-link into the conversation panel.
- Two real bugs found and fixed via live verification, not caught by
  type-check/lint: (1) daily trend bucketing was anchored on the range's
  *start* date and excluded today entirely, so a tenant's whole day of
  activity was invisible on every chart while still counting in the stat
  tiles above it; (2) the trend chart's fixed SVG viewBox was scaled down
  via CSS to fit a narrower card, which scaled text/stroke-width along
  with everything else — an 11px axis label was actually rendering at
  ~5 real pixels on a small-screen layout. Fixed by measuring the
  container via `ResizeObserver` and rendering at its real pixel width
  instead of relying on viewBox scaling.

**2026-08-03** — Two new nav pages, Channels and Integrations
(`frontend/src/pages/Channels.tsx`/`Integrations.tsx`), modeled on
reference mockups as UI scaffolding for a future phase — **both
deliberately static previews, no backend work at all** (confirmed
directly before building: real per-tenant channel data and real
e-commerce connectors both stay out of scope for now, see ARCHITECTURE
§10/§12). Channels lists the five real channel types with their real
Real/Simulated fact; Integrations lists five e-commerce platforms, all
permanently "Not connected." Every action button (Add channel/Test all
channels/Configure/Connect) renders disabled with a "coming soon"
tooltip. No fabricated numbers on either page — same rule as the
Dashboard build; the reference mockups' invented stats (active
conversation counts, satisfaction scores, sync timestamps) were dropped
entirely rather than faked.

**2026-08-03, same day** — Channels' "AI status" column made real: a
per-channel auto-reply on/off switch, backed by a new
`Channel.ai_enabled` column (migration, default on for every channel) and
two new endpoints (`GET /channels/connected`, `PATCH /channels/{id}`).
Deliberately gated where the pipeline turns a result into a customer-
facing reply (`app/pipeline/tasks.py`'s `_process_incoming_message` and
`_send_follow_up`), not before the pipeline runs — intent/lead-score/
escalation keep getting computed and logged either way, confirmed
directly with the user; only the actual send is suppressed. A
conceptual cousin of the cancelled per-conversation "human-paused
conversations" idea, but narrower (channel-wide, no human-send
capability) and not a reversal of that cancellation. `GET /channels`
deliberately isn't the bare collection-root route — `/channels` is also
a frontend page route now, so the endpoint lives at `/channels/connected`
instead, same fix `/knowledge/sources` already applies for `/knowledge`.

---

## Old section-number cross-reference

This file used to have numbered subsections (§2, §3.1–§3.8, §5.1–§5.5);
those numbers are gone as of the 2026-07-31 housekeeping pass, but dozens
of code comments across `backend/`/`frontend/` still cite them (e.g.
`docs/ROADMAP.md §3.1`). Not rewritten as part of this pass — that's
40+ files of comment churn, out of scope for a docs-only cleanup. Use
this table to resolve an old citation to where its content now lives
above:

| Old ref | Topic | Now under |
|---|---|---|
| §2 | Conversation history threading | Changelog, 2026-07-29 |
| §3.1 | Escalation cover reply + internal-note bubble | Changelog, 2026-07-29 |
| §3.2 | One clarifying question before escalating | Changelog, 2026-07-29 |
| §3.3 | Conversation rail intent/lead-score badges | Changelog, 2026-07-28 |
| §3.4 | Test Console per-message diagnostics | Changelog, 2026-07-28 |
| §3.5 | SSE live updates | Changelog, 2026-07-29 |
| §3.6 | `keep_chatting` knowledge-gap escalation fix | Changelog, 2026-07-29 |
| §3.7 | Typed per-tenant behavior config | Changelog, 2026-07-30 |
| §3.8 | Tenant settings API + UI | Changelog, 2026-07-30 |
| §5.1 | Multi-tenant showcase seed script | Changelog, 2026-07-29 |
| §5.4 | Dev-only tenant switcher | Changelog, 2026-07-29 |
| §5.5 | Knowledge source + trigger-phrase CRUD | Changelog, 2026-07-29 |

---

*See [`REQUIREMENTS.md`](REQUIREMENTS.md) for what/why and
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the current technical design.*
