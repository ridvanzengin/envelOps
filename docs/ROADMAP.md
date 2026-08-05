# EnvelOps — Roadmap & Current Status

> Living "what's next" document. [`REQUIREMENTS.md`](REQUIREMENTS.md)
> (what/why) and [`ARCHITECTURE.md`](ARCHITECTURE.md) (how) are the stable
> references; this document tracks *where things stand* and *what's still
> open* — not a full history of how each item got built. Detailed
> session-by-session narrative (what was tried, what broke, how it was
> verified) is not kept here once an item ships; the Changelog below is a
> one-line-per-item pointer, not a write-up. Reusable engineering gotchas
> (not just "this one bug") live in `CLAUDE.md` instead, so they survive
> this kind of pruning; deploy-specific failure modes live in
> `.claude/skills/deploy/SKILL.md` the same way.
>
> Housekeeping pass 2026-07-31: this file was ~1800 lines of full
> session write-ups. Condensed to open items + a compact changelog.
>
> Housekeeping pass 2026-08-05 (development for Phase 1 is now finished):
> back up to ~1030 lines — the same drift the first pass fixed, mostly
> from very detailed same-day changelog entries written during active
> development. Condensed again, same policy: check `git log --merges` /
> `gh pr view <N>` for the full narrative behind any entry below, not
> this file. Nothing below is deleted from history, only from this
> document — every PR still has its own full commit message.

---

## Current state (as of 2026-08-05)

**Phase 1 development is finished.** EnvelOps is a solo portfolio project
demonstrating AI behavior orchestration/safety/configuration — **not** a
product being shipped to a real business. The original pilot (a friend's
honey business) is deprioritized; see `REQUIREMENTS.md`'s own status
update at its top for the full scope-pivot reasoning. It's **live and
open source**:

- **Live at [envelops.site](https://envelops.site)**, in public read-only
  demo mode, deployed on a shared Hetzner VM alongside two sibling
  projects (IoTOps, AgriTwin). See `deploy/SERVER_SETUP.md` and
  `.claude/skills/deploy/SKILL.md` for the deployment topology and
  operating playbook.
- **Open source, MIT licensed** (`LICENSE`) — mentioned explicitly in the
  README and the in-app Documentation page, not just implied by a badge.
- **Telegram** is the one real channel integration. Instagram/WhatsApp/
  Facebook/Email are simulated (`app/channels/simulated_client.py`) — real
  pipeline, webhook-shaped entry points, no real platform contacted.
- Order-status/inventory lookup use **real** Gemini tool-calling over a
  **real** internal HTTP call (`app/commerce/connectors.py`) to a
  **fake** commerce-platform endpoint this same backend also mounts
  (`app/commerce/fake_platform_api.py`), grounded in a real, bounded
  per-tenant catalog — not a real Shopify/WooCommerce integration, never
  reachable from outside this backend.
- Turkish/bilingual pipeline support is cut, fully, including
  `escalation/safety_gate.py`'s own pattern lists. Frontend i18n UI chrome
  (`react-i18next`) is untouched and unrelated.
- Two calibration tenants are seeded (Wildroot Apparel Co, Voltage
  Gadgets), each run against real Bitext-sampled customer-support DMs via
  `scripts/seed_calibration_tenant.py` — the primary way tenant configs
  get exercised.
- Dashboard, Channels, Integrations, Test Console, Knowledge Sources, and
  Settings are all real, built-out screens — no placeholder pages remain.
  Integrations stays a deliberate static preview (real e-commerce
  connectors are out of scope); Channels lists real channels with a
  working per-channel AI auto-reply toggle, but channel *creation* is
  still script-only.
- A public, read-only demo mode exists (`ENVELOPS_DEMO_MODE_ENABLED`,
  `app/core/demo_mode.py`) — every mutating endpoint 403s, Test Console
  stays real but persistence-free, and the frontend skips login entirely
  in favor of a dropdown-menu tenant switcher. It's also what
  `stream_demo_dm`/`purge_stale_demo_data` (Celery Beat) key off to keep
  the live site feeling alive — 10–15 simulated inbound DMs/day across
  every tenant and all 5 channel types, with a rolling 7-day retention
  purge. Both jobs only ever run when `demo_mode_enabled` is on.
- The frontend has a mobile-device layout (off-canvas drawers for
  `Sidebar`/`ChannelRail`, a full-screen `ConversationPanel` overlay
  below 640px) — implemented but not yet live-verified in a real mobile
  viewport.
- 400+ backend tests pass, `ruff`/`mypy` clean; frontend `tsc -b`/
  `vite build`/`oxlint` clean. Check `gh pr list --state merged` rather
  than trusting a PR number in this file, which goes stale between
  sessions.

## Open items

Real, not yet designed in detail, not currently being worked:

- **Minor, not urgent**: ~10–15s per Test Console send (up to several
  sequential Gemini calls, none parallelized — `search_knowledge` doesn't
  actually depend on `understand_intent`'s output, so parallelizing those
  two is a viable future latency win).
- **A "Markdown" knowledge-source type** — deliberately excluded from the
  knowledge-sources redesign since it isn't real backend capability yet;
  would need a small ingestion addition, not a redesign.
- **Safety floor has no weapons/regulated-goods pattern category** —
  `escalation/safety_gate.py`'s Layer 1 only covers contraindication/
  symptom/outcome-guarantee language (all health-adjacent), so a weapons
  query never has a chance to trip it regardless of phrasing.
  Complementary to, not overlapping with, the bounded fake-commerce
  catalog fix — that only protects against *off-catalog* queries, not a
  tenant whose real catalog legitimately contains something regulated.
  Not yet designed in detail; likely shape is a new pattern category
  alongside the existing three, platform-enforced the same way.
- **Mobile UI not yet live-verified** in a real mobile viewport (see
  Current state above) — implemented from a reference pattern, drawer
  open/close wiring and z-index layering not yet empirically confirmed
  end to end.
- **Whether the deploy PRs' own commit messages are a sufficient
  changelog trace going forward**, now that this file's changelog is
  deliberately terse again — worth revisiting if that starts feeling
  thin in practice.

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
attribution and a multi-model prompt playground; human-paused
conversations (the conversation thread view's read-only state is a
settled design choice, see ARCHITECTURE §10); channel failure behavior
beyond the health-check stub; data retention/deletion policy specifics;
and whether/when general draft-and-approve comes back — Phase 1's
auto-send + safety-floor-escalation-only gate (ARCHITECTURE §5) stays
final, not provisional.

## Changelog

Terse, newest first — one entry (or a short group) per work session, PR
number where known. Full detail lives in `git log --merges` / `gh pr
view <N>`, not here.

**2026-08-05** — Open-sourced under MIT (`LICENSE`; README and in-app
docs both mention it explicitly, not just via a badge); in-app docs'
test-count stat refreshed and a Demo Mode feature card added (PR #68).
This file (and `REQUIREMENTS.md`/`ARCHITECTURE.md`, checked but left
alone — see their own housekeeping notes) condensed as part of the same
pass.

**2026-08-05** — Fixed a production nginx routing gap: `/conversations/`
and `/escalations/` nested paths (message loading, escalation resolve,
trigger-phrase CRUD) had no trailing-slash `location` block and silently
fell through to the SPA instead of the backend — the first real bug
surfaced by production traffic, after a celery-beat-streamed conversation
failed to open on the rail (PR #67).

**2026-08-05** — First production launch, https://envelops.site, on the
shared Hetzner VM already hosting IoTOps/AgriTwin (PRs #59–64: `deploy/`
infra, docker-compose, nginx vhost, systemd unit, deploy skill). Three
live deploy bugs found and fixed the same day: backend Dockerfile missing
`alembic`/`scripts/` in its `COPY` list, celery-beat OOM-crash-looping at
an inherited 128M memory limit (bumped to 256M), and a calibration seed
script's hardcoded `localhost:8000`. Postgres-15's schema-level `GRANT`
requirement and demo-mode's Test-Console-discard behavior both documented
in `deploy/SERVER_SETUP.md`/the deploy skill rather than code-fixed.

**2026-08-05** — Deleted stale `scripts/seed_showcase_tenants.py` (predated
the Turkish cut, superseded live by `seed_calibration_tenant.py`,
deliberately deleted from production) and its dependent
`scripts/run_bitext_stress_test.py`, plus a cascade of stale
cross-references found from checking (PR #65). Also fixed, unrelated to
git history: a stray local-only `.env` line breaking `Settings()`.

**2026-08-05** — Mobile-device UI added: `Sidebar`/`ChannelRail` become
off-canvas drawers, `ConversationPanel` becomes a full-screen overlay,
below a shared 640px breakpoint — structured directly after IoTOps's own
mobile pattern (new `useMediaQuery` hook, same z-index scheme) (PR #58).

**2026-08-05** — Test Console polish, IoTOps's `CopilotChat`/
`AiGenerationError` pattern as the explicit reference: optimistic send +
an inline cycling "Thinking" indicator (replacing a frozen "Sending..."
button state), and a new `AiProviderError` + global exception handler
turning any Gemini failure into a friendly 502 instead of a raw
uncaught 500 (PR #56).

**2026-08-05** — Demo-stream messages diversified beyond knowledge
questions — weighted, randomized purchase-intent/hot-lead/complaint/
escalation-trigger template pools added alongside the original pool;
channel-level reply formality narrowed to email-only; a Voltage Gadgets
international-shipping knowledge gap closed; FAQ (`url`) and Terms of
Service (`pdf`) knowledge sources added for both calibration tenants,
rounding out all three source types (PR #55 follow-ups).

**2026-08-05** — Lightweight demo DM streaming (`stream_demo_dm`, 10–15
simulated inbound DMs/day across all 5 channel types) plus a rolling
7-day retention purge (`purge_stale_demo_data`), both demo-mode-gated
Celery Beat jobs — Test Console's own demo-mode path never touched the
real conversation rail at all, so a passive visitor never saw anything
move before this (PR #55).

**2026-08-04** — Fake-commerce/tool-calling hardening, several rounds of
live-found-and-fixed bugs the same day: catalog matching moved from
exact-match to whole-word containment (a plural or a dropped word no
longer produces a false "not carried"); a `[Live lookup result]` tag
that leaked into replies verbatim; `INVENTORY_CHECK_TOOL`'s description
too narrow to catch "do you sell X" phrasing; `keep_chatting`
mis-tagging a correct negative tool answer as a knowledge gap instead of
relaying it; `decide_next_step`'s hot-lead fast path skipping grounding
entirely (the same fabrication class the fake-commerce platform exists
to close, reached via a different route). Wildroot given tool-calling +
a catalog (previously only Voltage Gadgets had it) (PRs off the
fake-commerce-platform branch, same day).

**2026-08-04** — Built the real-HTTP fake commerce platform
(`app/commerce/fake_platform_api.py`, a bounded per-tenant
`FakeCommerceProduct` catalog), closing a live-found fabrication bug:
the old hash-seeded `check_inventory` gave a plausible in-stock answer
for literally any product string, including "ak47." Full root-cause
writeup: [`docs/plans/fake-commerce-platform-integration.md`](plans/fake-commerce-platform-integration.md).

**2026-08-04** — Removed the separate `dev_auth_bypass_enabled` flag and
Login's own dev-only tenant switcher — demo mode is now the sole
no-password login mechanism (`/auth/demo-tenants`/`/auth/demo-login`).

**2026-08-04** — Public read-only demo mode added
(`ENVELOPS_DEMO_MODE_ENABLED`): every mutating endpoint 403s at the API
layer, Test Console stays real but persistence-free (swaps in an
in-memory LangGraph checkpointer), and the frontend replaces the login
screen with a tenant-switcher dropdown.

**2026-08-03** — Fixed the Celery worker's asyncpg cross-event-loop bug
(found live in PR #47): a `NullPool`-backed `worker_async_session`
added for Celery-task DB access, kept separate from the pooled
FastAPI-facing session — full gotcha writeup in `CLAUDE.md`. Real
Dashboard page shipped the same window (stat tiles, trend chart,
intent-breakdown donut, per-channel table, knowledge status — PR #46).
Two new nav pages, Channels and Integrations, added as static previews;
Channels later gained a real per-channel AI auto-reply on/off switch.

**2026-07-28 to 2026-07-31** — Conversation rail intent/lead-score
badges and per-message diagnostics; conversation history threading, SSE
live rail updates, natural escalation cover replies (PRs #25–34); typed,
bounded per-tenant behavior configuration (`TenantBehaviorConfig`) plus
a tabbed Settings UI with independent per-tab save (PRs #35–36).

**2026-07-31 — portfolio scope pivot** (direct instruction, full
reasoning in `REQUIREMENTS.md`'s own status update at its top): the real
pilot (a friend's honey business) is deprioritized, EnvelOps becomes a
solo portfolio project. Turkish/bilingual support cut everywhere,
including the safety gate's own pattern lists; real Instagram/WhatsApp/
Facebook/commerce integrations cut in favor of simulated channels + real
Gemini tool-calling over fake deterministic connectors; tenant count
capped at ~2 rather than growing across every vertical; template gallery
and AI copilot cut as predicated on the abandoned multi-vertical
ambition (PR #37). Two real calibration findings fixed same window (a
fabricated support-email workflow, an order-modify request misrouted
into `book_or_checkout` — PRs #38–39); safety-floor efficacy-cue gap
closed (PR #40); UI polish pass, PDF knowledge sources, Knowledge
sources page full redesign (PRs #41–43). Also this day: this file's
first housekeeping pass, ~1800 lines → open items + changelog (PR #45).

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
| §2 | Conversation history threading | Changelog, 2026-07-28 to 2026-07-31 |
| §3.1 | Escalation cover reply + internal-note bubble | Changelog, 2026-07-28 to 2026-07-31 |
| §3.2 | One clarifying question before escalating | Changelog, 2026-07-28 to 2026-07-31 |
| §3.3 | Conversation rail intent/lead-score badges | Changelog, 2026-07-28 to 2026-07-31 |
| §3.4 | Test Console per-message diagnostics | Changelog, 2026-07-28 to 2026-07-31 |
| §3.5 | SSE live updates | Changelog, 2026-07-28 to 2026-07-31 |
| §3.6 | `keep_chatting` knowledge-gap escalation fix | Changelog, 2026-07-28 to 2026-07-31 |
| §3.7 | Typed per-tenant behavior config | Changelog, 2026-07-28 to 2026-07-31 |
| §3.8 | Tenant settings API + UI | Changelog, 2026-07-28 to 2026-07-31 |
| §5.1 | Multi-tenant showcase seed script (deleted 2026-08-05) | Changelog, 2026-08-05 |
| §5.4 | Dev-only tenant switcher (removed 2026-08-04) | Changelog, 2026-08-04 |
| §5.5 | Knowledge source + trigger-phrase CRUD | Changelog, 2026-07-28 to 2026-07-31 |

---

*See [`REQUIREMENTS.md`](REQUIREMENTS.md) for what/why and
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the current technical design.*
