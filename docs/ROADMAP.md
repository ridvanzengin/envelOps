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

## Current state (as of 2026-07-31)

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
- All PRs through #43 are merged into `main`. Always check `gh pr view <N>
  --json state` before trusting a specific PR's status — this file goes
  stale between sessions.

## Open items

Real, not yet designed in detail, not currently being worked:

- **Full observability dashboard** — builder's trace view vs. business
  owner's operational view, likely two separate views.
  `pipeline_traces`/rail badges/Test Console diagnostics already populate
  the data this would be built on. The one open item actively worth
  building next — most showable feature on the list, and the data's
  already there.
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
#43).

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
