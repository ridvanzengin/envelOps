# EnvelOps — Architecture (Phase 1)

> Working name: **EnvelOps**. This is the technical companion to
> [`REQUIREMENTS.md`](REQUIREMENTS.md) — that document is the fixed reference
> for *what* is being built and *why*; this one is *how*, for Phase 1
> specifically (§13 of the requirements doc: core pipeline, tenant-isolated
> data model, auto-send with a hard safety gate, static knowledge, one
> real channel plus simulated ones).
>
> **STATUS UPDATE (2026-07-31):** Turkish/English pipeline language
> support (originally listed here) is cut, not built — §7. Real live-data
> connectors and real channels beyond Telegram are cut in favor of
> simulated versions — §6, §8, §12. See REQUIREMENTS.md's own status
> update at its top for the full reasoning (the real pilot this was all
> scoped around is deprioritized).
>
> Phase 2+ (graph-augmented retrieval, fine-tuning, template gallery, roles,
> the deferred items below) are intentionally not designed in detail here —
> revisit this document when that work starts.

---

## 1. Tech stack

- **Backend:** Python, FastAPI, domain-module structure (`auth/`, `tenants/`,
  `channels/`, `conversations/`, `knowledge/`, `pipeline/`, `leads/`,
  `escalation/`), each with `api.py` / `service.py` / `repository.py` /
  `models.py` — same pattern as IoTOps
- **Canonical schema:** Pydantic models, single source of truth across
  API/DB/pipeline state
- **Pipeline engine:** LangGraph — runs the fixed 8-step sequence (not a
  user-editable canvas; see REQUIREMENTS §3). Chosen specifically
  for native checkpoint/resume support, which the safety-escalation pause
  needs (see §5).
- **Relational + vector store:** Postgres with the `pgvector` extension — one
  service instead of a separate vector DB, since graph retrieval and the
  template gallery are both deferred. Migrating to a dedicated vector DB later
  is a contained change (swap the retrieval query), not a rewrite.
- **LLM + embedding provider:** Gemini (`google-genai`), covering
  generation, embeddings, and (as of 2026-07-31) real tool-calling through
  one API key — `app.core.llm`'s `generate_text` / `embed_text` /
  `generate_with_tools`. Chosen originally for its free tier (REQUIREMENTS
  §12's synthetic-testing phase needed a $0 starting point). One real
  gotcha worth knowing before picking a model name: free-tier quota is
  granted per model, not per key/project, and a specific model can sit at
  a permanent zero on an otherwise-working account (a 429 that never
  recovers, easy to mistake for a temporary rate limit) — see `CLAUDE.md`
  for the exact models that do/don't currently work on this account.
- **Task queue:** Celery + Redis (message processing handoff, knowledge
  re-sync, follow-up delays, channel health checks)
- **Messaging ingestion:** Telegram Bot API is the one real channel
  (plain `httpx` against Telegram's Bot API, §8) — Beeper (the originally-
  planned primary multi-channel bridge for WhatsApp/Instagram/Facebook
  Messenger) was **never built**; Telegram turned out to be the more
  useful first channel (no bridge infrastructure, just a bot token), and
  Beeper's own unofficial-bridge limitation stopped mattering once the
  decision below made it moot anyway. **Instagram/WhatsApp/Facebook/Email
  are simulated, not real** (decided 2026-07-31, §8) — webhook-shaped
  entry points into the same real pipeline, no real platform (Meta or
  otherwise) ever contacted; building real integrations for these was
  judged out of scope for what this project demonstrates.
- **Frontend:** React
- **Deployment:** Docker Compose — **one shared deployment, multiple tenants**
  (you host it), not one deployment per business. This is the reason tenant
  isolation is a data-model requirement from day one, not a nice-to-have.

## 2. Tenancy & auth

- Every table carries `tenant_id` directly. Repositories filter by tenant as
  standard practice; row-level security in Postgres is the safer enforcement
  point, not something trusted to always be remembered in application code.
- Vector search is tenant-scoped (a `tenant_id` filter on every pgvector
  query), so retrieval never crosses tenant boundaries.
- Auth: JWT-based, tenant id embedded in the token. **Single "owner" role for
  Phase 1** — the schema has a `role` column ready for a narrower staff role
  later, but only one role actually exists yet.
- Explicitly deferred (product surface, not data model): self-serve signup,
  billing, a tenant-admin UI, subdomain-per-business routing.

## 3. Data model

Core tables (Phase 1): `tenants`, `users`, `channels`, `conversations`,
`messages`, `leads`, `knowledge_sources`, `knowledge_chunks` (pgvector
embedding column), `escalations`, `escalation_trigger_phrases`
(tenant-added Layer 1 additions, see §5), `pipeline_traces`, and a
checkpoint table for LangGraph's pause/resume state (see §5).

Key relationships: a tenant has many users/channels/knowledge sources; a
channel routes to many conversations; a conversation contains many messages,
optionally produces one lead, and may have escalation records.

`tenants.closing_action` is REQUIREMENTS §2's "what closing looks like must
be configurable per business" requirement, concretely: one of the pipeline's
own branch names (`keep_chatting` | `escalate_to_human` | `book_or_checkout`)
rather than a separate "business model" concept translated into one, since
nothing else needs that indirection yet. Defaults to `escalate_to_human` —
autonomous closing is opt-in, not the default.

**Note:** `draft_replies` was designed earlier in this process (draft-and-
approve on every message) but is **not part of Phase 1** — see §5.

## 4. Conversation pipeline

Fixed 8-step sequence, run by LangGraph, same for every business (no visual
builder in Phase 1 — see REQUIREMENTS §3). The graph's actual node list is
longer than 8 — `load_history`, `check_pending_escalation`,
`load_tenant_config`, and (2026-07-31) `call_tools` are all prerequisite/
interstitial nodes around the original numbered steps, not steps
themselves:

1. Incoming message (normalized from channel)
2. Understand intent
3. Search knowledge base (vector-only; pgvector similarity search, tenant-
   scoped, top-k chunks assembled into the generation prompt)
4. Score the lead (hot/warm/cold — plain LLM call for now; fine-tuning is a
   later-phase quality improvement, not required to function)
5. Decide next step (based on intent + score) — purely deterministic/
   code-driven routing (safety-floor regex, hot-lead gating); the LLM is
   never part of this decision, only ever invoked afterward to produce
   prose for whichever branch was already picked
6. Branch: keep chatting / escalate to human / book-or-checkout. On the
   `keep_chatting` branch specifically, a `call_tools` node (2026-07-31)
   runs first — real Gemini tool-calling (`app.core.llm.generate_with_tools`):
   if the tenant has a fake connector enabled (`ToolCallingConfig`, §6) and
   the model decides the message needs one, it calls a fake, deterministic
   order-status/inventory connector (`app/commerce/`) and folds the result
   into `keep_chatting`'s existing knowledge-context block, alongside
   `retrieved_chunks` — same downstream STATUS-tag/escalation machinery
   either way, no parallel reply path. Inert (zero extra Gemini calls) for
   every tenant that hasn't opted in.
7. Log lead & notify team
8. Follow up after delay (Celery job scans quiet conversations, re-enters at
   step 2 if the lead replies)

State object carried through the run: `tenant_id`, `conversation_id`,
`incoming_text`, `channel_type`, `conversation_history` (prior messages
in the conversation, populated by the graph's own `load_history` node,
not by any caller), `tenant_behavior_config` (raw
dict, §6), `detected_intent`, `retrieved_chunks`, `tool_call_results`
(2026-07-31 — one formatted fact string per successful fake tool call,
same shape/spirit as `retrieved_chunks`), `lead_score`, `decision`,
`draft_text`, `escalation_reason` (if any), `escalation_logged` (§5's
double-log guard). This state is what gets checkpointed at the pause
point (§5) — every new field added to it has followed the same rule:
plain primitives/dicts only, never a nested Pydantic model, since a
nested model's behavior under LangGraph's own state serializer across a
pause/resume boundary is untested risk not worth taking.
`pipeline_traces` (defined alongside the rest of the data model but
unused for a while) gets one row per inbound message (`detected_intent`/
`lead_score`/`decision` only, not the full state) — both the real
Telegram path (`pipeline/tasks.py`) and Test Console
(`app/test_console/api.py`) write it now, via the same
`PipelineTraceRepository.record_result` helper. The future observability
dashboard can still largely be built by widening this same mechanism
rather than inventing new logging.

`channel_type` drives reply tone/structure in step 6's `keep_chatting`/
`book_or_checkout` branches, and is now genuinely **tenant-configurable**
(not true when this paragraph was first written): `app/pipeline/behavior.py`'s
`render_channel_tone` reads a per-tenant `channel_overrides` map
(`TenantBehaviorConfig`, §6) with a system-default fallback
(`_SYSTEM_DEFAULT_CHANNEL_TONE_TEXT` in the same file — email gets a
greeting, fuller sentences, and a sign-off by default; Telegram/WhatsApp/
Instagram/Facebook stay short and casual by default) when a tenant hasn't
overridden it. Configurable via Settings' "Platform-specific tone" tab
(§10). Verified via the Test Console (§9, §10), not the synthetic
harness — tone is a presentational property the harness's "does this look
right to a human" standard doesn't really cover; the real check is
sending the same question through multiple channels and comparing.

## 5. Human-in-the-loop: safety gate only, not general approval

**Decided in this session:** general draft-and-approve on every outbound
message is cut from Phase 1 — it added real day-to-day burden (an owner
babysitting every message) for a trust benefit that most competitors solve by
auto-sending and gating only on exceptions instead.

**What stays, unconditionally:** the platform-enforced safety floor from
REQUIREMENTS §6. The pipeline auto-sends by default; the *only* pause point is
when the safety check (contraindication language, symptom/complaint language,
outcome-guarantee requests) trips. That pause uses LangGraph's native
checkpoint/resume — the graph saves state and waits, however long it takes a
human to act, then resumes.

This means: no approval-queue UI for every message, no general timeout/
notification design needed yet — only the escalation path needs a "human
review" screen, and that screen already had to exist regardless (it's the
same mechanism as the safety floor, not a new one). If general draft-approval
is wanted later, it's a contained addition (one more pause point, one more
queue), not a rewrite — see §11.

**Layer 1 trigger phrases (REQUIREMENTS §6): system defaults + tenant
additions, checked together.** System defaults are the compiled regex
patterns in `escalation/safety_gate.py` (`check_platform_safety_floor`);
tenant additions live in `escalation_trigger_phrases` (tenant-scoped, one
row per phrase, no category/regex — a business owner types a phrase, not
a pattern) and are matched as plain case-insensitive substrings, not
compiled into the regex list. `decide_next_step` (§4) checks both and
escalates if either fires — whichever runs first, the result is the same
hard gate. The UI (§10) shows system defaults as visible but disabled/
locked (no edit, no delete) and lets the tenant append to *and delete
from* their own list (`DELETE /escalations/trigger-phrases/{id}`, added
2026-07-29 — REQUIREMENTS §6 has the full reasoning for allowing removal
after all); there is no code path or API endpoint that edits or removes
a system default, by design, not just by UI omission — that part is
still fully immutable.

**The Escalation row is logged by `decide_next_step`, before the pause —
not by `log_lead_and_notify` after a resume.** A human has to be able to
*see* an escalation to know to resume it; logging it only after something
resumes it is circular. `log_lead_and_notify` also logs an Escalation
whenever `decision == escalate_to_human` when it runs (needed for
`book_or_checkout`'s own, unrelated escalate-on-missing-`closing_link`
case, which never pauses and so never hits `decide_next_step`'s logging)
— `PipelineState.escalation_logged` (set by `decide_next_step`'s
safety-floor branch, right after it logs the row) is what tells
`log_lead_and_notify` not to log the same one again on resume. Fixed once
`POST /escalations/{id}/resolve` (§9) landed and gave `resume_pipeline()`
its first real caller — this used to be a known, harmless-until-something-
calls-resume gap; it isn't anymore.

**A second way `decision` becomes `escalate_to_human`, besides the safety
floor — `decide_next_step`'s hot+purchase-intent branch, when
`tenant.closing_action` is `escalate_to_human`** (the *default* for every
tenant that hasn't opted into `book_or_checkout` — `Tenant.closing_action`'s
own docstring). Found and fixed via real Test Console usage (§9, §10), not
synthetic testing — the synthetic tenant always sets
`closing_action="book_or_checkout"`, so this path never ran there. Before
the fix: this routed straight to `escalate_to_human`'s `interrupt()`
without ever setting `escalation_reason` or logging an Escalation row
first, exactly the "logged after the pause is circular" problem the
paragraph above already solved for the safety floor — so for the
*default* tenant config, every hot purchase-intent message silently
paused the pipeline forever: no reply, no Escalation a human could ever
see or resolve. Now logs immediately (`layer="business_rule"`, distinct
from the safety floor's `platform_floor`) before the pause, same as the
safety-floor branch.

## 6. Knowledge ingestion & retrieval

**Static sources** (URL, PDF, manual entry): fetch/extract text → chunk
(~300–500 tokens, overlap) → embed via Gemini (§1) → store in
`knowledge_chunks` (tenant-scoped, pgvector). A manual "refresh this source"
action deletes and re-embeds a source's chunks — no silent staleness.

**API-reachable now** (`POST`/`GET`/`PUT`/`DELETE /knowledge/sources`,
`POST /knowledge/sources/{id}/refresh`, all auth-gated): `manual` (owner
pastes text directly) and `url` (fetched via a plain httpx GET,
`app/knowledge/web_fetch.py` — same "thin client, not a heavier SDK"
reasoning as the Telegram client) both work end to end with zero new
dependencies — `app/knowledge/html_text.py` strips HTML to plain text
using stdlib `html.parser`, not a new parsing library. Deliberately not
attempted: schema.org FAQPage structured Q&A parsing (§5's "parsed as
clean Q&A pairs where available" — text-only fallback is what's built).
Refresh only makes sense for `url` sources (400 for `manual`). `PUT`
(added 2026-07-29) is refresh's manual-only mirror — replaces a source's
chunks with newly-chunked/re-embedded
user-submitted text; 400s for `url` sources for the same reason refresh
400s for `manual` ones, so editing a url source's fetched content by hand
can't be silently clobbered by the next refresh. `GET` now also returns
each source's `content` (its chunks rejoined with `"\n\n"`, not a second
copy of the text stored anywhere) — before this, a source's actual
content was never visible anywhere in the API, only its metadata.

**`pdf` is not built** — the model's `type` column already anticipates it,
but ingesting one needs a real PDF-parsing library (pypdf or similar), a
new dependency deliberately deferred to its own follow-up rather than
bundled with the zero-new-dependency `manual`/`url` work above.

**Live data** (inventory, pricing): explicitly not embedded — matches
REQUIREMENTS §5's original reasoning either way. **A simulated version now
exists (2026-07-31), a real platform connector still doesn't and isn't
planned to.** Real Gemini tool-calling (`app.core.llm.generate_with_tools`,
§4's `call_tools` node) backed by fake, deterministic connectors
(`app/commerce/connectors.py` — hash-seeded, same input always the same
fake output, no DB table, no real network call) for order-status and
inventory lookups. REQUIREMENTS §5's "connect your store" real-platform
path and manual-CSV fallback are both still exactly as undesigned as
before.

**Retrieval at reply-time:** embed the incoming question, pgvector cosine-
similarity search scoped to tenant, top-k chunks into the generation prompt.
Vector-only — graph-augmented retrieval is designed (REQUIREMENTS §10) but
not built until a relationally-complex business type is actually being
onboarded.

**Per-tenant behavior configuration** (`app/tenants/behavior_config.py`'s
`TenantBehaviorConfig`, built 2026-07-30 — undocumented here until this
housekeeping pass): bounded, typed, versioned Pydantic schema controlling
how the pipeline talks, not what it decides. One sub-model per area
(`greeting`, `off_topic`, `knowledge_query`, `complaint`, `lead_handling`,
`escalation_cover`, `book_or_checkout`, `tool_calling`) plus
`channel_overrides` (per-platform tone) and a top-level `general_context`
escape hatch. Two deliberate conventions load-bearing for elasticity:
`extra="ignore"` (not Pydantic's default `"forbid"` — a stored config from
an older/newer schema version deserializes without raising) and every
value field is `Literal`-typed, not plain `str` (so the frontend can
derive dropdown/radio options directly from the schema, no separate
options list to keep in sync). Each area's own `additional_context` field
is explicitly **data, never behavior** — a fact the model is told to be
aware of, never composed into new decision logic — the same shape
`escalation_trigger_phrases` (§5) already uses, and the actual reason
free-text "AI personality" instructions were never considered: bounded
fields avoid the competing-instructions failure class that motivated this
design (found live, `keep_chatting` — see `docs/ROADMAP.md`).

Stored as one `Tenant.behavior_config` JSON column, loaded once per
pipeline run (`load_tenant_config` node) as a **raw dict**, not the typed
model — same checkpointer-safety reasoning as the rest of `PipelineState`
(§4). `app/pipeline/behavior.py` has one `render_*` function per area,
turning the typed config into the actual prompt text `app/pipeline/graph.py`'s
nodes send to the model; every one is held to a byte-identical-at-defaults
bar (called with an all-defaults config, returns exactly what the
hardcoded pre-refactor string produced), which is what let the existing
test suite pass unmodified when this was introduced.

**API + UI**: `GET`/`PATCH /tenants/settings` (`app/tenants/api.py`, added
2026-07-30 — missing from §9 below until this pass) — `PATCH` takes one
tab's own slice at a time (e.g. `{"greeting": {...}}`), never the whole
object, so the Settings UI's per-tab independent-save behavior (§10) is
real, not simulated client-side: saving one tab genuinely cannot touch
another tab's unsaved edits, because the request never carries them.

## 7. Language support (Turkish + English) — **CUT (2026-07-31)**

This was built and working (see the original description kept below), but
is now cut, not a live capability — REQUIREMENTS §11 has the full
reasoning (written for a Turkish pilot business that's now deprioritized).
The generation-side behavior described below (detect-and-match reply
language) has been removed from the actual prompts in
`app/pipeline/graph.py` — replies are now effectively always whatever
language the model defaults to, regardless of input language. Embeddings/
retrieval were never made language-aware beyond the base model's own
ability, so nothing changed there. The frontend `react-i18next` setup
(§10) is untouched and still works — it was always independent of pipeline
language handling, not affected by this cut.

**Follow-up (same day):** `escalation/safety_gate.py`'s Turkish pattern
lists (contraindication/symptom/certainty/efficacy cues) were also
removed — system defaults are English-only now, matching the rest of the
pipeline. Tenant-added trigger phrases (REQUIREMENTS §6) are unaffected,
since that's a plain substring match with no language dependency to begin
with.

Original design (summary, not in effect): reply-generation prompts
instructed the model to detect and match the incoming message's language
(verified working both directions before the cut); embedding-level
cross-lingual retrieval quality was never actually tested; the frontend's
`react-i18next` setup (§10) was, and still is, entirely independent of
both.

## 8. Channel ingestion & background jobs

**Telegram is the one real channel** (`POST /channels/telegram/{channel_id}/webhook`,
plain `httpx` against Telegram's Bot API — deliberately not the
`python-telegram-bot` SDK, whose polling/dispatcher machinery is for a
different, long-running-process pattern than one-shot webhook receive/
respond): validate the `X-Telegram-Bot-Api-Secret-Token` header (fails
closed if the channel has no secret configured, not just on a mismatch) →
`_ingest_inbound_message` (shared helper, below) → hand off to a Celery
task (kept out of the webhook handler itself, so Telegram gets a fast
response) → that task runs the pipeline and sends the reply back via
`sendMessage`. `scripts/register_telegram_channel.py` creates the
`Channel` row and calls `setWebhook` — no API/UI for this yet (channel
connection isn't part of the API surface until real auth exists).
**Beeper was never built** — Telegram turned out to be the more useful
first channel to actually implement (no bridge infrastructure, just a bot
token), not just a "fallback."

**Instagram/WhatsApp/Facebook/Email are simulated, not real (2026-07-31)**
— `POST /channels/{instagram,whatsapp,facebook,email}/{channel_id}/webhook`
(`app/channels/api.py`), each parsing a payload shape plausible for that
platform (`app/channels/simulated_client.py` — deliberately flattened,
not full fidelity to Meta's real envelope) then calling the same
`_ingest_inbound_message` helper Telegram uses, so it's genuinely the same
pipeline/persistence path, not a parallel one. Auth is one uniform
EnvelOps-owned header (`X-EnvelOps-Simulated-Webhook-Secret`) checked
against `Channel.webhook_secret`, not each platform's real signing
scheme — building real per-platform signature verification for fake
integrations would be exactly the over-engineering this simulation
avoids. `scripts/register_simulated_channel.py` creates the `Channel` row
(`is_test=False`, `bot_token=None`) — no real API calls, since there's
nothing real to register with. **Outbound send needs zero special-casing
for these**: `pipeline/tasks.py`'s existing `if channel.bot_token:` guard
(below) already no-ops for any channel without one, while still
persisting the outbound `Message` row — a simulated channel's reply is
fully visible in the UI, it just never attempts a real network call.
`_ingest_inbound_message` (shared by all five channels, real and
simulated alike): find-or-create the `Conversation` (by external contact
id, `app/conversations/repository.py`'s `get_by_external_contact`) →
persist the inbound `Message` → commit → publish the live-update SSE
event → hand off to the `process_incoming_message` Celery task.

**Test Console channels** (`app/test_console/api.py`) — a *third*,
distinct mechanism from both of the above, not to be confused with the
simulated channels: `Channel.is_test` flags a lazily-created, one-per-
(tenant, type) channel with no webhook of any kind behind it, for any of
the five rail channel types. `GET /test/conversations`/
`POST /test/conversations/messages` (§9) call `run_pipeline` directly and
synchronously (a human is watching, no webhook needing a fast response),
and every conversation it produces carries `is_test=True` — shown with a
visible "Test" badge in the UI (§10), unlike a simulated channel's
conversations, which are `is_test=False` and read as genuine inbound DMs.
Existed before the simulated channels did, and still serves a different
purpose: quick manual exploration/debugging of the pipeline for any
channel type, without needing a `Channel` row set up first.

**Background jobs (Celery):**
- `process_incoming_message` — **built.** Runs the pipeline for one
  message; on `__interrupt__` it commits without replying (the escalation
  was already logged by `decide_next_step` before the pause — see §5);
  otherwise it logs the outbound message and attempts a real send only
  when `channel.bot_token` is set (Telegram today), catching and logging
  (not swallowing, not raising) a delivery failure so an outage doesn't
  lose the Lead/Message rows already written. Channel-agnostic otherwise —
  simulated channels flow through the exact same task.
- `knowledge_resync` — not built. Manual trigger now (`POST
  /knowledge/sources/{id}/refresh`, §6/§9), could become scheduled later.
- `follow_up_check` — **built.** The only periodic job so far, run by
  Celery Beat (`docker-compose.yml`'s `beat` service; a separate
  process from the `worker` — both must be running) every 30 minutes.
  Scans across *all* tenants (`ConversationRepository.list_quiet_unscoped`
  — a deliberate, narrow exception to tenant-scoped queries, same
  reasoning as `ChannelRepository.get_by_id_unscoped`: a periodic
  background job has no per-request tenant context to scope by) for
  conversations whose most recent message is outbound, more than
  `settings.follow_up_delay_hours` (default 24) old, and not yet
  followed up. Sends exactly one generated check-in message ever per
  conversation — `Conversation.followed_up_at` caps it; if the lead
  replies at any point, that's a normal inbound message through the
  usual channel-ingestion path, re-entering the pipeline at step 2 like
  any other reply, not something this job needs to handle itself.
- `channel_health_check` — not built, minimal stub only planned; the real
  "what happens when a channel disconnects" design is still an open item
  (see §11).

## 9. API surface (Phase 1)

`/auth`, `/channels`, `/knowledge`, `/conversations`, `/leads`,
`/escalations`, `/dashboard`, `/test`, `/events`, `/tenants` — one router
per domain module, matching the `api.py` per module convention. `/test`
(`app/test_console/api.py`) and `/events` (`app/events/api.py`, SSE live
updates) are both exceptions with no `models.py`/`repository.py` of their
own — `/test` reuses `Channel`/`Conversation`/`Message` as-is (§8),
`/events` has no DB table at all. `/channels` now has five real routes
(one webhook per channel type, §8), not just Telegram's.

**`/tenants`** (`app/tenants/api.py`, added 2026-07-30 — missing from
this list until this housekeeping pass): `GET`/`PATCH /tenants/settings`,
the API behind §6's per-tenant behavior configuration and the Settings
UI's tabbed "AI behavior & business settings" section (§10). `PATCH`
takes one tab's own slice at a time, not the whole object — see §6 for
why that's structural, not cosmetic.

`GET /conversations` takes an optional `channel_type` query param (one
rail icon's worth of conversations at a time, ChannelRail/
ConversationPanel — §10); its response and `GET /escalations`'s both
carry `channel_type`/`is_test` per row now (joined through to `Channel`),
which is what the frontend's per-channel escalation badges and Test
badge key off.

**Auth is real now:** `POST /auth/login` (email + password → JWT, tenant id
and role embedded per §2) and `GET /escalations` (the first real protected
endpoint, gated by `app.auth.dependencies.get_current_user` — a Bearer JWT
dependency that trusts the signature/expiry rather than re-querying the
user per request, since Phase 1 has no revocation list and only one role).
`users.email` is globally unique, not per-tenant scoped — login has no
tenant selector, so email is how the tenant gets discovered, the same
reasoning as `ChannelRepository.get_by_id_unscoped` (CLAUDE.md), landed
here as `UserRepository.get_by_email_unscoped`.

`GET /escalations` lists pending + resolved rows for the caller's tenant.
`POST /escalations/{id}/resolve` marks one resolved and calls
`resume_pipeline()` (§5) to unpause its checkpointed thread — no request
body: Phase 1 has no draft-and-approve mechanism (§5), and
`escalate_to_human`'s `interrupt()` doesn't consume a resume value for
anything, so there's nothing for a reply-text field to do yet. Resolving
here does **not** send anything to the customer; the human handles the
actual reply outside the tool. 409s if the escalation isn't `pending`
(prevents resuming an already-resumed thread twice).

`/knowledge` is real now too (§6: create/list/refresh a source, and, as
of 2026-07-29, `DELETE /knowledge/sources/{id}` — cascades to that
source's `knowledge_chunks` via `KnowledgeChunkRepository.delete_by_source`,
the same method `refresh` already used).

`GET`/`POST`/`DELETE /escalations/trigger-phrases` — the tenant-additions
half of §5's Layer 1 trigger phrases; delete added 2026-07-29 (§5 above
has the full reasoning). Still no edit endpoint — a business owner
deletes and re-adds to change a phrase, same as a knowledge source.
System defaults have nothing to list here since they're compiled regex in
`safety_gate.py`, not DB rows — the frontend shows those as static,
translated copy instead (§10), and there is still no code path that
edits or removes *those*.

`/conversations` is real now too: `GET /conversations` (list, with each
conversation's most recent message as a preview — one query via
`ConversationRepository.list_with_last_message`, same "one query, not
list-then-fetch-per-row" reasoning as `KnowledgeSourceRepository.
list_with_chunk_counts`) and `GET /conversations/{id}/messages` (full
thread, oldest first).

Still empty routers, wired into `main.py` but with nothing behind them:
`/channels` (besides its five webhooks, §8 — still no channel-management
CRUD), `/leads`, `/dashboard`.

## 10. Frontend screens (Phase 1)

A design-token system now backs the whole frontend (`frontend/src/index.css`
— CSS variables for color/spacing/shadow, teal/blue accent, dark-default
with a light toggle via `data-theme` on `<html>`, set pre-paint by an inline
`index.html` script reading `localStorage` so there's no flash of the wrong
theme). A persistent `Sidebar` (left) replaces the old flat `<nav>`, with
`ThemeContext`/`useTheme` following the same 3-file split as the existing
`AuthContext`/`useAuth`. Structurally modeled on a sibling project's mature
frontend as a *reference only* (shared token/shell shape, not its domain
features) — see that project's own docs if touching this area, the pattern
isn't repeated here.

- **Login** — real now: email/password against `POST /auth/login` (§9),
  token kept in `localStorage`, gates the whole app (single owner role,
  §2 — one gate is enough, no per-route permission model needed yet). The
  language switcher deliberately lives outside this gate (`App.tsx`), not
  inside the post-login nav — this is dashboard UI chrome (still English/
  Turkish, unaffected by §7's pipeline-language cut), and was built when
  the owner reading it in Turkish mattered; now just a working, harmless
  affordance no longer load-bearing for a real pilot.
- **Conversations (right-side rail + panel, not a routed page)** — real
  now, but no longer an "Inbox" nav item or route. A fixed icon rail on
  the right (`ChannelRail`, one icon per channel type: Telegram, WhatsApp,
  Facebook, Instagram, Email) is persistent across every authenticated
  route. Every icon shows a **Real** or **Simulated** integration label
  on hover (`isRealChannel`, `frontend/src/lib/channels.ts` — the one
  shared source of truth for the channel-type list, consolidated
  2026-07-31 from three previously-independent duplicated copies) — only
  Telegram is real, the other four are simulated webhook-shaped entry
  points (§8), not merely "Test Console only" the way this line used to
  read. A simulated channel's real conversations (created via its own
  webhook, `is_test=False`) show up exactly like Telegram's; Test
  Console's own conversations (`is_test=True`, any channel type) are the
  ones that get the small Test badge. Clicking a rail icon opens a
  sliding panel
  (`ConversationPanel`) showing that channel's conversations as a list
  (`GET /conversations?channel_type=...`), then a conversation's full
  thread (`GET /conversations/{id}/messages`) with direction-based bubble
  alignment. A conversation whose channel is `is_test` shows a small Test
  badge next to its status. The thread view is **read-only** by design,
  not by omission (2026-07-31, `docs/ROADMAP.md`) — it shows a reply input
  + send button, both permanently disabled: a human sending a message
  outside the pipeline (the "human-paused conversations" mode once
  considered for this) was cut as a real-business-ops concern this
  project isn't demonstrating, not deferred as a placeholder waiting on
  backend work.
- **Escalations (folded into the same rail/panel, not a standalone page)**
  — the old dedicated Escalation queue page and nav item are gone.
  `GET /escalations` is instead fetched once at the app-shell level and
  correlated by `conversation_id`, client-side, into: a **per-channel-type**
  pending-count badge on each rail icon (`channel_type` now travels on
  each escalation row, §9), an "Escalated" filter toggle scoped to the
  currently-open channel's conversation list, and a Resolve action
  (`POST /escalations/{id}/resolve`) inside a conversation's thread view
  when it has a pending escalation. No backend *schema* change for any of
  this beyond the `channel_type`/`is_test` fields already covered in §9 —
  still a client-side correlation, just now aware of more than one
  channel at a time. The primary "action needed" surface, since auto-send
  is the default and escalations are the one thing routinely waiting on a
  human.
- **Test console** (`/test`, new nav item) — lets the tenant owner send a
  message through the real pipeline against any of the five channel
  types, to validate reply tone/behavior (§4) before a real integration
  exists for that channel. A platform dropdown plus an always-enabled
  input (the one place in the app where a human's text actually reaches
  the pipeline directly) send to `POST /test/conversations/messages`;
  switching platforms re-fetches that channel's one ongoing test
  conversation via `GET /test/conversations`. An escalated test message
  shows an inline notice instead of a reply, and resolves through the
  exact same rail/panel Resolve action as any other escalation — no
  separate resolve UI for test conversations.
- **Knowledge sources** — real now: add (manual or url — pdf isn't built
  on the backend yet, §6, so there's no third form option), list with
  chunk counts, refresh (url only; no button shown for manual rows,
  matching the backend's 400), and delete (any type, added 2026-07-29 —
  in-place removal from the list, same as everything else here, no
  refetch). Same fetch/update pattern used for escalation resolution
  (§10 above). Each row also has a chevron toggle (added 2026-07-29,
  alongside delete) that expands/collapses the source's actual content
  read-only — before this, a source's content was never shown anywhere
  in the UI, only its metadata (a real gap, found via live use, not by
  design). Manual rows additionally get a pencil button turning that same
  expanded area into an editable textarea (Save calls the new `PUT`);
  url rows stay view-only, matching the backend's url/manual split.
- **Settings** — two columns (added 2026-07-30, after a first single-
  column pass proved the wrong shape live): "Safety trigger phrases" (§5)
  on the right — three static, translated category labels for the system
  defaults (disabled checkboxes, no edit/delete control, ever — there's
  nothing to fetch for them, they're not DB rows) plus a real
  list-add-and-delete form for the tenant's own additions (§9; delete
  added 2026-07-29, §5's reasoning) — and "AI behavior & business
  settings" on the left, real and tabbed (`/tenants/settings`, §6/§9):
  Closing, Greeting, Off-topic, Knowledge, Complaints, Leads, Escalation,
  Booking, **Tool calling** (added 2026-07-31, alongside the tool-calling
  feature itself — an on-purpose gap-close, this tab and its `PATCH`
  support didn't exist when `ToolCallingConfig` itself first shipped),
  Platform-specific tone, General. **Each tab saves independently** — its
  own Save button, `PATCH`ing only that tab's own slice (§6) — not one
  form-wide save; a real, deliberate design point (proven live: editing
  one tab without saving it, then saving a different tab, does not carry
  the first tab's unsaved edit along). The Tool calling tab carries an
  explicit "uses simulated demo data, not a real connected store" notice
  — there's no credentials/connection UI anywhere in Settings, since
  there's nothing real to connect (§6). Channel connection status
  (registering a new Telegram bot, or a simulated channel, from the UI)
  is still not built — both remain script-only (§8).
- **Dashboard** — real now (2026-08-01, `GET /dashboard/summary`,
  `app/dashboard/`), no longer a placeholder: stat tiles (conversations,
  messages, hot leads, escalations, avg response time — REQUIREMENTS §9's
  original "leads today, escalations today, response times" list),
  a daily trend chart, a conversations-by-intent breakdown, a per-channel
  resolution-rate table, knowledge base status, and recent escalations
  (deep-links into the conversation panel on click). One unified view,
  not the two-audience (builder/owner) split originally scoped — see
  REQUIREMENTS §9 for why that held up fine at this project's data
  volumes. Every chart is hand-rolled SVG, no new frontend dependency —
  `frontend/src/components/dashboard/`.
- **Channels** and **Integrations** (2026-08-03, `frontend/src/pages/
  Channels.tsx`/`Integrations.tsx`) — two new nav items, both
  **deliberately static previews, no backend behind either one.**
  Channels lists the five real `CHANNEL_TYPES` with their real
  Real/Simulated fact (`isRealChannel()`, the same one `ChannelRail.tsx`
  already shows) and a static "Auto-reply: Always on" label (this app has
  no per-channel-type AI on/off switch to wire up); Integrations lists
  Shopify/WooCommerce/BigCommerce/Magento/PrestaShop, every row
  permanently "Not connected." "Add channel"/"Test all channels"/
  "Configure"/"Connect" all render disabled with a "coming soon" tooltip
  — real channel creation stays script-only (§8), and real e-commerce
  connectors stay exactly as cancelled as §12 already has them. **Adding
  these nav items does not reverse that cancellation** — flagged
  explicitly so the nav item's mere existence is never read as evidence
  the decision changed; re-litigate §12 directly if it ever should.
  Neither page fabricates a number anywhere (no message/conversation/
  satisfaction/sync counts) — same rule the Dashboard build settled on.

Dev-only CORS avoidance: `frontend/vite.config.ts` proxies each backend
router prefix (`/auth`, `/escalations`, ...) to `localhost:8000` so the
frontend can call relative paths without the browser treating it as
cross-origin. No CORS middleware on the backend, and no production
frontend-origin story yet — neither is designed.

No drag-and-drop flow builder in Phase 1.

## 11. Open items carried forward (non-blocking, not designed yet)

See [`ROADMAP.md`](ROADMAP.md) for the up-to-date, actively-maintained
version of this list, current status, and priority order — that document
now owns tracking "what's next," so it doesn't drift out of sync with a
second copy here. Kept brief in this document because these are
architectural gaps, not day-to-day status:

No open items carried here as of 2026-08-01 — the full observability
dashboard (the last one) is built, see §10. Check `docs/ROADMAP.md`'s own
Open items section before assuming that still holds; new gaps get
scoped there first, this section only follows once one lands here too.

**Cut, not open items anymore (2026-07-31)**, see `docs/ROADMAP.md`:
~~`book_or_checkout` beyond a static link~~ (a real Shopify/WooCommerce/
Calendly connector — `book_or_checkout` still always sends the same
tenant-configured static `Tenant.closing_link`); ~~human-paused
conversations~~ (the conversation panel's thread view stays read-only by
design now, §10, not as a placeholder for this); ~~channel failure
behavior beyond the health-check stub~~; ~~data retention/deletion policy
specifics~~; ~~whether/when general draft-and-approve gets added back~~
(REQUIREMENTS §4) — all real-business-ops concerns judged out of scope
for what this portfolio project demonstrates, same logic as §12's cuts
below.

## 12. Explicitly deferred to later phases

Graph-augmented retrieval, embedding/lead-scoring fine-tuning,
multi-user roles beyond "owner," the visual flow builder. See
`REQUIREMENTS.md` §10, §13 for the full reasoning on each.

**Cut, not deferred (2026-07-31, REQUIREMENTS §10)** — don't move these
back to this list without re-litigating the decision: real live-data/
platform-API connectors (Shopify/WooCommerce/etc.) and real channel
integrations beyond Telegram, both replaced by a **simulated** version
instead (§6, §8); the starter template gallery and AI-assisted
configuration, both predicated on the multi-vertical tenant breadth the
2026-07-31 portfolio-scope pivot walked back from. **Still true as of
2026-08-03** despite the new Channels/Integrations nav pages (§10) —
those are static UI previews, not a reversal; see §10's own note.

---

*This document plus `REQUIREMENTS.md` together are the reference for
starting Phase 1 development. See [`ROADMAP.md`](ROADMAP.md) for current
status and next steps.*
