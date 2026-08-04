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

## Current state (as of 2026-08-04)

EnvelOps is a solo portfolio project demonstrating AI behavior
orchestration/safety/configuration — **not** a product being shipped to a
real business. The original pilot (a friend's honey business) is
deprioritized; see the Changelog's 2026-07-31 entries for the full
scope-pivot reasoning. Concretely, right now:

- **Telegram** is the one real channel integration. Instagram/WhatsApp/
  Facebook/Email are simulated (`app/channels/simulated_client.py`) — real
  pipeline, webhook-shaped entry points, no real platform contacted.
- Order-status/inventory lookup use **real** Gemini tool-calling over a
  **real** internal HTTP call (`app/commerce/connectors.py`) to a
  **fake** commerce-platform endpoint this same backend also mounts
  (`app/commerce/fake_platform_api.py`, 2026-08-04), grounded in a real,
  bounded per-tenant catalog — not a real Shopify/WooCommerce
  integration, never reachable from outside this backend.
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
- A public, read-only demo mode exists (`ENVELOPS_DEMO_MODE_ENABLED`,
  `app/core/demo_mode.py`) — every mutating endpoint 403s, Test Console
  stays real but persistence-free, and the frontend skips login entirely
  in favor of a real dropdown-menu tenant switcher on the Dashboard. The
  old, separate `dev_auth_bypass_enabled` flag and Login page's own
  dev-only tenant switcher are gone (decided 2026-08-04) — demo mode is
  now the single no-password-login mechanism, at `/auth/demo-tenants` +
  `/auth/demo-login` (renamed from `/auth/dev-tenants`/`/auth/dev-login`).
  See the changelog entries below for the full shape.
- All PRs through #50 are merged into `main` (confirmed via `gh pr view
  50 --json state` 2026-08-04) — **check this**: verify the actual PR
  number/state with `gh pr list`/`gh pr view <N> --json state` rather
  than trusting this file, which goes stale between sessions.

## Open items

Real, not yet designed in detail, not currently being worked:

- **Minor, not urgent**: ~10–15s per Test Console send (up to several
  sequential Gemini calls, none parallelized — `search_knowledge` doesn't
  actually depend on `understand_intent`'s output, so parallelizing those
  two is a viable future latency win).
- **A "Markdown" knowledge-source type** — deliberately excluded from the
  knowledge-sources redesign (PR #43) since it isn't real backend
  capability yet; would need a small ingestion addition, not a redesign.
- **Safety floor has no weapons/regulated-goods pattern category**, found
  2026-08-04 the same session as the bounded-commerce-catalog fix below
  (see that changelog entry) — `escalation/safety_gate.py`'s Layer 1 only
  covers contraindication/symptom/outcome-guarantee language (all
  health-adjacent), so a weapons query never has a chance to trip it
  regardless of phrasing. Complementary to, not overlapping with, that
  fix — the bounded catalog only protects against *off-catalog* queries,
  not a tenant whose real catalog legitimately contains something
  regulated. Not yet designed in detail; likely shape is a new pattern
  category alongside the existing three, platform-enforced the same way.

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

**2026-08-04, later still** — Built the real-HTTP fake commerce platform
planned earlier the same day
([`docs/plans/fake-commerce-platform-integration.md`](plans/fake-commerce-platform-integration.md)),
fixing the live-found bug where `check_inventory`'s hash-seeded logic
fabricated a plausible in-stock answer for *any* product string
regardless of what a tenant actually sells (found via Test Console: "do
you have ak47 in stock?" got a confident, ordinary answer).
- New `FakeCommerceProduct` table (`app/commerce/models.py`,
  tenant-scoped, one migration) — a bounded per-tenant catalog; a query
  with no matching row now genuinely comes back "not carried."
- New internal-only router `app/commerce/fake_platform_api.py`
  (`/internal/fake-commerce/products`, `/internal/fake-commerce/orders/
  {order_number}`), bearer-token-gated
  (`ENVELOPS_FAKE_COMMERCE_INTERNAL_TOKEN`, fail-closed), mounted by this
  same backend and never reachable from outside it. The order-status
  endpoint keeps the exact same hash-seeded logic the old in-process
  connector had (moved server-side, not changed) — no bounded
  fake-orders table, since an arbitrary-looking order number is a normal
  thing for a real customer to type, unlike an unbounded product string.
- `app/commerce/connectors.py` rewritten as real async `httpx` calls to
  that endpoint (`ENVELOPS_INTERNAL_API_BASE_URL`, `localhost:8000` for
  host dev, `http://backend:8000` for the backend/worker containers —
  same override pattern as the database/redis URLs); never raises, a
  timeout/connection failure/non-2xx degrades to `None` same as
  `execute()`'s existing hallucinated-tool-name handling.
  `call_tools`/`tools.execute()` both became `async` to thread this
  through; `InventoryResult` gained a `carried: bool` field so "off
  catalog" and "carried but out of stock" render as distinct, honest
  replies.
- `scripts/seed_calibration_tenant.py`: new `TenantSpec.catalog` field,
  seeded for Voltage Gadgets only (the one calibration tenant with
  `inventory_check_enabled=True`).
- Live-verified through the real pipeline, not just unit tests: asking
  Voltage Gadgets' AI about a real catalog item returned the seeded
  quantity; asking about AK-47 rifles returned "We do not carry AK-47
  rifles, as there is no matching product in our catalog." Also verified
  the worker container resolves the internal base URL correctly and can
  reach the backend container by service name.
- Does **not** fix the safety-floor weapons/regulated-goods pattern gap
  (separate, still-open item above) — this closes the *fabrication*
  path, not the *escalation* path, by design (see the plan doc's own
  non-goals).
- 12 migrations now (was 7 in CLAUDE.md's stale count, corrected same
  session), 352 backend tests pass, `ruff`/`mypy` clean.

**2026-08-04, later same day** — Removed the separate `dev_auth_bypass_enabled`
flag and Login page's own dev-only tenant switcher entirely, direct
instruction, now that demo mode covers the same no-password-login need:
- Backend: `dev_auth_bypass_enabled` deleted from `config.py`.
  `/auth/dev-tenants`/`/auth/dev-login` renamed to `/auth/demo-tenants`/
  `/auth/demo-login` (`DevTenantOption`→`DemoTenantOption` etc.), gated
  solely by `demo_mode_enabled` now — the OR-condition is gone since
  there's only one flag left.
- Two calibration/stress-test scripts (`seed_calibration_tenant.py`,
  `run_bitext_stress_test.py`) used the old dev-login purely as a
  no-password auth convenience, unrelated to demo mode as a product
  feature — switched to logging in for real via `POST /auth/login` with
  the known `DEMO_PASSWORD` each seeded tenant's owner already gets, so
  neither script depends on `demo_mode_enabled` at all. Deliberate: that
  flag also makes Test Console stop persisting messages
  (`_send_test_message_demo`), which would have silently defeated both
  scripts' actual purpose (real, inspectable seeded message history) if
  left depending on it.
- Found via this: the test suite reads the same real `.env` file as the
  dev server, so turning `demo_mode_enabled` on there to actually view
  the demo locally 403'd 57 unrelated tests. Fixed with a new
  `tests/conftest.py` autouse fixture forcing `settings.demo_mode_enabled
  = False` before every test (individual demo-mode tests still patch it
  True within their own scope) — the suite no longer depends on whatever
  a developer's local `.env` happens to be set to.
- Frontend: `Login.tsx` back to a plain email/password form, no dev
  dropdown, no `useDevTenants` import. `useDevTenants` renamed
  `useDemoTenants` (`/auth/demo-tenants`), consumed by `App.tsx`'s
  auto-login and `Dashboard.tsx`'s tenant dropdown only — Login.tsx isn't
  a consumer anymore. Removed now-unused `auth.devBadge`/
  `auth.devTenantSwitch*` i18n keys and `.login-page__dev-switch`/
  `.dev-badge` CSS in both locales.
- `.claude/skills/run/SKILL.md` updated to match: no more manual
  `<select>`/`selectOption` login step to drive a session (demo mode
  auto-logs in on page load now) — the Dashboard's own tenant dropdown
  is how a driven session switches tenants, keyed by `tenant_id`, not
  `user_id` like the old Login dropdown was.
- 337 backend tests pass (7 dev-bypass tests consolidated into 5
  demo-mode-only ones, since the OR-condition scenario no longer exists
  to test separately). Frontend build/lint clean.

**2026-08-04** — Public read-only demo mode (`demo` branch, not yet a
PR), direct instruction: a single `ENVELOPS_DEMO_MODE_ENABLED` flag turns
the whole app into a safe-to-share showcase.
- Backend: every mutating endpoint (knowledge source CRUD, `PATCH
  /tenants/settings`, escalation resolve + trigger-phrase add/delete, the
  channel AI toggle, all 5 inbound channel webhooks) 403s via a shared
  `app/core/demo_mode.py` dependency — enforced at the API layer, not
  just a frontend disable, per direct instruction. `follow_up_check`
  (Celery Beat) skips entirely, since it isn't reachable through the API
  gate at all. `demo_mode_enabled` also ORs into the existing dev-auth-
  bypass gate (`auth/api.py`), opening the no-password tenant switcher.
- Test Console is the deliberate exception: still runs the real pipeline
  (real Gemini calls, real knowledge search) but never creates a
  Channel/Conversation row or writes a Message/PipelineTrace row —
  swaps the Postgres checkpointer for an in-memory one and keeps
  per-session history in a process-local dict instead, keyed the same
  way a real Conversation lookup would be. Response shape unchanged, so
  the frontend needed no changes there specifically.
- Frontend: `App.tsx` skips the login screen entirely in demo mode
  (auto dev-logs-in as the first showcase tenant via `GET
  /system/demo-mode` + `GET /auth/dev-tenants`); the Dashboard's own
  `<h1>` becomes a "Tenant: [dropdown]" selector in its place, reading
  the current tenant from the JWT itself (`src/lib/jwt.ts`, client-side
  decode, no new endpoint needed). Every mutating control across
  Knowledge/Settings/Channels/escalation-resolve gets `disabled` (not
  hidden — direct instruction: full functionality stays visible, only
  alterations are cut) plus a `title` tooltip, and a persistent sidebar
  badge reminds a visitor throughout, not just per-button on hover.
  `CHANNEL_ICONS` (`ChannelRail.tsx`'s dev-tenants list, now also needed
  by `App.tsx` and `Dashboard.tsx`) got pulled into shared hooks
  (`useDevTenants`, `useDemoMode`) and a `DemoModeProvider` context
  rather than fetched independently per page.
- 339 backend tests pass (22 new, covering the 403 gate across every
  route, the dev-auth-bypass OR, `follow_up_check`'s skip, and Test
  Console's persistence-free path including multi-turn continuity across
  two messages in the same session). Frontend build/lint clean.

**2026-08-03, later same day** — Fixed the Celery worker asyncpg
cross-event-loop bug (found live during PR #47, filed not fixed there —
see that PR's own write-up) on its own branch/session as planned
(`fix/celery-asyncpg-event-loop`). Root cause confirmed
by isolated repro first (two sequential `asyncio.run()` calls against the
shared pooled engine, outside Celery entirely): the second call reliably
raised the same `RuntimeError: ... attached to a different loop`, then an
`InterfaceError` on the third — reproducing the exact live symptom before
touching any code. Fix: `app/core/db.py` now exposes a second,
`NullPool`-backed engine/sessionmaker (`worker_engine`/
`worker_async_session`) used only by `app/pipeline/tasks.py` (imported
under the existing `async_session` name so the rest of that file, and the
existing test suite's `patch("app.pipeline.tasks.async_session", ...)`
targets, didn't need to change) — NullPool opens/closes a real connection
per checkout instead of reusing one across event-loop boundaries, the same
"accept per-call connect overhead, stay loop-safe" tradeoff
`app/core/events.py`'s `publish_event()` already made for Redis. The
FastAPI-facing `engine`/`async_session` stay pooled, unchanged — uvicorn's
one long-lived loop was never actually affected by this bug, so there was
no reason to give up pooling there too. Verified, not just reasoned
through: the isolated repro script passed cleanly post-fix (3/3 calls
succeeded); `pytest -q` (317 passed), `ruff check`, `mypy` all clean; then
a live end-to-end pass against the real docker-compose stack — worker
restarted for a clean warm process, 20 real webhook POSTs fired at a real
simulated Instagram channel in quick succession (deliberately more than
the worker's prefork concurrency of 11, to force multiple tasks onto the
same child process, matching the original failure shape) — zero
`different loop`/`InterfaceError` occurrences in worker logs across all
20. (Incidentally tripped the tenant's Gemini free-tier per-minute quota
from the burst — expected, unrelated, self-recovered; verification
conversations/messages/leads/traces cleaned up from the DB afterward
rather than left as noise on a real tenant.) `follow_up_check` shares the
same fix since it also now runs under `worker_async_session`, though its
30-minute cadence made it unlikely to double-fire against one warm process
in practice either way.

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
