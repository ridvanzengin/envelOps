# EnvelOps — Architecture (Phase 1)

> Working name: **EnvelOps**. This is the technical companion to
> [`REQUIREMENTS.md`](REQUIREMENTS.md) — that document is the fixed reference
> for *what* is being built and *why*; this one is *how*, for Phase 1
> specifically (§13 of the requirements doc: core pipeline, tenant-isolated
> data model, auto-send with a hard safety gate, static knowledge, one
> channel, Turkish/English language support).
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
- **LLM + embedding provider:** Gemini (`google-genai`), covering both
  generation and embeddings through one API key — chosen for its free tier
  (REQUIREMENTS §12's synthetic-testing phase needs a $0 starting point).
  One real gotcha worth knowing before picking a model name: free-tier
  quota is granted per model, not per key/project, and a specific model can
  sit at a permanent zero on an otherwise-working account (a 429 that never
  recovers, easy to mistake for a temporary rate limit) — see `CLAUDE.md`
  for the exact models that do/don't currently work on this account.
- **Task queue:** Celery + Redis (message processing handoff, knowledge
  re-sync, follow-up delays, channel health checks)
- **Messaging ingestion:** Beeper Desktop API (webhooks) as the primary
  multi-channel bridge (WhatsApp/Instagram/Facebook Messenger/Telegram);
  Telegram Bot API also wired as a lower-risk fallback channel. Known
  limitation: Beeper's bridges are unofficial, not Meta's Business Cloud API —
  acceptable for now, flagged for a production swap-out later.
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
builder in Phase 1 — see REQUIREMENTS §3):

1. Incoming message (normalized from channel)
2. Understand intent
3. Search knowledge base (vector-only; pgvector similarity search, tenant-
   scoped, top-k chunks assembled into the generation prompt)
4. Score the lead (hot/warm/cold — plain LLM call for now; fine-tuning is a
   later-phase quality improvement, not required to function)
5. Decide next step (based on intent + score)
6. Branch: keep chatting / escalate to human / book-or-checkout
7. Log lead & notify team
8. Follow up after delay (Celery job scans quiet conversations, re-enters at
   step 2 if the lead replies)

State object carried through the run: `tenant_id`, `conversation_id`,
`incoming_text`, `channel_type`, `detected_intent`, `retrieved_chunks`,
`lead_score`, `decision`, `draft_text`, `escalation_reason` (if any),
`escalation_logged` (§5's double-log guard). This state is what
gets checkpointed at the pause point (§5) and is most of what a
`pipeline_traces` row records — the future observability dashboard can
largely be built by surfacing this object rather than inventing new logging.

`channel_type` drives reply tone/structure in steps 6's `keep_chatting`/
`book_or_checkout` branches (`app/pipeline/graph.py`'s
`_CHANNEL_TONE_GUIDANCE`) — email gets a greeting, fuller sentences, and a
sign-off; Telegram/WhatsApp/Instagram/Facebook stay short and casual, no
greeting or sign-off. First-pass and generic, not tenant-configurable yet,
same status as the intent-label/lead-score taxonomies above. Verified via
the Test Console (§9, §10), not the synthetic harness — tone is a
presentational property the harness's "does this look right to a human"
standard doesn't really cover; the real check is sending the same question
through multiple channels and comparing.

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
additions, checked together, additive only.** System defaults are the
compiled regex patterns in `escalation/safety_gate.py`
(`check_platform_safety_floor`); tenant additions live in
`escalation_trigger_phrases` (tenant-scoped, one row per phrase, no
category/regex — a business owner types a phrase, not a pattern) and are
matched as plain case-insensitive substrings, not compiled into the regex
list. `decide_next_step` (§4) checks both and escalates if either fires —
whichever runs first, the result is the same hard gate. The UI (§10) shows
system defaults as visible but disabled/locked (no edit, no delete) and
lets the tenant append to their own list; there is no code path or API
endpoint that edits or removes a system default, by design, not just by
UI omission.

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

## 6. Knowledge ingestion & retrieval

**Static sources** (URL, PDF, manual entry): fetch/extract text → chunk
(~300–500 tokens, overlap) → embed via Gemini (§1) → store in
`knowledge_chunks` (tenant-scoped, pgvector). A manual "refresh this source"
action deletes and re-embeds a source's chunks — no silent staleness.

**API-reachable now** (`POST /knowledge/sources`, `GET /knowledge/sources`,
`POST /knowledge/sources/{id}/refresh`, all auth-gated): `manual` (owner
pastes text directly) and `url` (fetched via a plain httpx GET,
`app/knowledge/web_fetch.py` — same "thin client, not a heavier SDK"
reasoning as the Telegram client) both work end to end with zero new
dependencies — `app/knowledge/html_text.py` strips HTML to plain text
using stdlib `html.parser`, not a new parsing library. Deliberately not
attempted: schema.org FAQPage structured Q&A parsing (§5's "parsed as
clean Q&A pairs where available" — text-only fallback is what's built).
Refresh only makes sense for `url` sources (400 for `manual` — nothing
external to re-fetch; delete and re-add instead).

**`pdf` is not built** — the model's `type` column already anticipates it,
but ingesting one needs a real PDF-parsing library (pypdf or similar), a
new dependency deliberately deferred to its own follow-up rather than
bundled with the zero-new-dependency `manual`/`url` work above.

**Live data** (inventory, pricing): explicitly not embedded. Deferred past
Phase 1 in practice — Phase 1 ships static knowledge only; live-data
connectors (platform API or manual CSV fallback) are a later addition, per
REQUIREMENTS §5.

**Retrieval at reply-time:** embed the incoming question, pgvector cosine-
similarity search scoped to tenant, top-k chunks into the generation prompt.
Vector-only — graph-augmented retrieval is designed (REQUIREMENTS §10) but
not built until a relationally-complex business type is actually being
onboarded.

## 7. Language support (Turkish + English)

Phase 1 requirement (REQUIREMENTS §11), driven by the pilot business
(REQUIREMENTS §12) being Turkish. Three separate concerns, not one:

- **Generation (pipeline steps 2 and beyond, §4)**: no separate translation
  step or language field the pipeline branches on — the intent-understanding
  and reply-generation prompts instruct the model to detect and reply in the
  incoming message's language. This rides on the base LLM's existing
  multilingual ability, not a bespoke component. Verified live for
  `understand_intent`/`score_lead`/`keep_chatting` — Turkish in, Turkish out,
  English in, English out, correct in both directions.
- **Embeddings (§6)**: same-language retrieval (English query against
  English-embedded chunks) is verified live. Cross-lingual retrieval quality
  specifically (a Turkish query against English-embedded chunks, or vice
  versa) has **not** been tested yet — worth checking before trusting it,
  not an assumption to leave unchecked just because a provider is picked.
- **Frontend (§10)**: a standard React i18n setup (e.g. `react-i18next`),
  independent of the two items above — this is the dashboard's own language
  switch for the business owner, unrelated to what language the pipeline
  detects in a customer's DM.

Not designed yet: whether `detected_intent`/pipeline state needs an explicit
`detected_language` field (for logging/observability) or the prompt handles
it implicitly without one — a Phase 1 implementation detail, not a
Phase 1 scope question.

## 8. Channel ingestion & background jobs

**Telegram is built** (`POST /channels/telegram/{channel_id}/webhook`,
plain `httpx` against Telegram's Bot API — deliberately not the
`python-telegram-bot` SDK, whose polling/dispatcher machinery is for a
different, long-running-process pattern than one-shot webhook receive/
respond): validate the `X-Telegram-Bot-Api-Secret-Token` header (fails
closed if the channel has no secret configured, not just on a mismatch) →
normalize into `messages` (look up or create the conversation by external
contact id, `app/conversations/repository.py`'s `get_by_external_contact`)
→ hand off to a Celery task (kept out of the webhook handler itself, so
Telegram gets a fast response) → that task runs the pipeline and sends the
reply back via `sendMessage`. `scripts/register_telegram_channel.py`
creates the `Channel` row and calls `setWebhook` — no API/UI for this yet
(channel connection isn't part of the API surface until real auth exists).
**Beeper is not built** — Telegram turned out to be the more useful first
channel to actually implement (no bridge infrastructure, just a bot
token), not just a "fallback."

**Test Console channels** (`app/test_console/api.py`) — `Channel.is_test`
flags a lazily-created, one-per-(tenant, type) channel with no real
webhook/API behind it, for any of the five rail channel types (Telegram/
WhatsApp/Instagram/Facebook/Email). Lets the pipeline's channel-aware
reply tone (§4) and the safety gate (§5) be exercised end-to-end, on
channels that don't have a real integration yet, before building one.
`GET /test/conversations`/`POST /test/conversations/messages` (§9) call
`run_pipeline` directly and synchronously — no Celery hand-off, since a
human is watching and there's no webhook needing a fast response. A test
conversation's `is_test` (via its channel) is what the frontend's Test
badge and `GET /conversations`'s/`GET /escalations`'s `channel_type`/
`is_test` fields key off (§9, §10).

**Background jobs (Celery):**
- `process_incoming_message` — **built.** Runs the pipeline for one
  message; on `__interrupt__` it commits without replying (the escalation
  was already logged by `decide_next_step` before the pause — see §5);
  otherwise it logs the outbound message and sends it via Telegram,
  catching and logging (not swallowing, not raising) a delivery failure so
  a Telegram outage doesn't lose the Lead/Message rows already written.
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
`/escalations`, `/dashboard`, `/test` — one router per domain module,
matching the `api.py` per module convention. `/test` (`app/test_console/
api.py`) is the one exception with no `models.py`/`repository.py` of its
own — reuses `Channel`/`Conversation`/`Message` as-is (§8).

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

`/knowledge` is real now too (§6: create/list/refresh a source).

`GET`/`POST /escalations/trigger-phrases` — the tenant-additions half of
§5's Layer 1 trigger phrases. List-and-add only, no delete/edit endpoint
(`TenantTriggerPhrase`'s own docstring: additive only). System defaults
have nothing to list here since they're compiled regex in
`safety_gate.py`, not DB rows — the frontend shows those as static,
translated copy instead (§10).

`/conversations` is real now too: `GET /conversations` (list, with each
conversation's most recent message as a preview — one query via
`ConversationRepository.list_with_last_message`, same "one query, not
list-then-fetch-per-row" reasoning as `KnowledgeSourceRepository.
list_with_chunk_counts`) and `GET /conversations/{id}/messages` (full
thread, oldest first).

Still empty routers, wired into `main.py` but with nothing behind them:
`/channels` (besides the webhook, §8), `/leads`, `/dashboard`.

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
  inside the post-login nav — a Turkish-speaking owner needs it to read
  the login screen itself, not just the app after logging in (§7).
- **Conversations (right-side rail + panel, not a routed page)** — real
  now, but no longer an "Inbox" nav item or route. A fixed icon rail on
  the right (`ChannelRail`, one icon per channel type: Telegram, WhatsApp,
  Facebook, Instagram, Email) is persistent across every authenticated
  route. All five are clickable now (§8's Test Console channels are what
  made this possible for the four without a real integration) — Telegram
  is the only one with any real conversations, the other four only ever
  show Test Console conversations. Clicking one opens a sliding panel
  (`ConversationPanel`) showing that channel's conversations as a list
  (`GET /conversations?channel_type=...`), then a conversation's full
  thread (`GET /conversations/{id}/messages`) with direction-based bubble
  alignment. A conversation whose channel is `is_test` shows a small Test
  badge next to its status. The thread view is **read-only** — it shows a
  reply input + send button, but both render permanently disabled, since
  there's no backend capability yet for a human to send a message outside
  the pipeline (see the pause-mode item in §11); it's a placeholder for
  that future affordance, not a working one.
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
  matching the backend's 400). Same fetch/update pattern used for
  escalation resolution (§10 above) — in-place update on the response, no
  refetch.
- **Settings** — partially real: the safety trigger phrase list (§5) is
  built — three static, translated category labels for the system
  defaults (disabled checkboxes, no edit/delete control, ever — there's
  nothing to fetch for them, they're not DB rows) plus a real
  list-and-add form for the tenant's own additions (§9). Channel
  connection status is not built — no `GET /channels` endpoint exists
  yet to show it.
- **Dashboard** — still a placeholder; minimal for Phase 1 (leads today,
  escalations today, response times) once built. The full two-audience
  observability design is still an open item (see §11).

Dev-only CORS avoidance: `frontend/vite.config.ts` proxies each backend
router prefix (`/auth`, `/escalations`, ...) to `localhost:8000` so the
frontend can call relative paths without the browser treating it as
cross-origin. No CORS middleware on the backend, and no production
frontend-origin story yet — neither is designed.

No drag-and-drop flow builder in Phase 1.

## 11. Open items carried forward (non-blocking, not designed yet)

- **Human-paused conversations (pause AI replies, reply directly without
  triggering an escalation)** — explicitly deferred out of the frontend
  redesign that added the conversation panel (§10). A real new backend
  feature: a second conversation-level pause mode alongside the existing
  safety-floor escalation (§5), needing a `Conversation` mode field,
  pause/resume + human-send endpoints, and a `process_incoming_message`
  check to skip the AI while paused. Until this lands, the panel's thread
  view stays read-only.
- **`book_or_checkout` beyond a static link** — implemented and verified
  with a tenant-configured URL (`Tenant.closing_link`), which is enough for
  any business regardless of platform. A real Shopify/WooCommerce/Calendly
  *connector* (auto-generating a checkout/booking link per order rather
  than sending the same static one) is REQUIREMENTS §13's own step 2
  ("live data connection... for platforms that support it"), not step 1 —
  correctly-sequenced-later work, not a gap, and needs a product decision
  on which connector(s) to build first, not just an engineering pass.
- Channel failure behavior beyond the health-check stub — silent stop vs.
  detected fallback. Telegram (§8) doesn't have even a stub yet, only
  Beeper was ever planned to.
- Full observability dashboard (builder's trace view vs. owner's operational
  view — likely two different views, not one)
- Data retention/deletion policy specifics
- Whether/when general draft-and-approve gets added back, and if so, whether
  certain categories "graduate" to auto-send based on approval history (the
  data hook for this — approved-as-is vs. edited vs. rejected — should still
  be captured wherever it's cheap to log, even without the feature)
- ~~A synthetic-message test harness for pipeline validation~~ — built:
  `backend/scripts/run_synthetic_conversations.py` runs a fixed set of
  fabricated DMs (REQUIREMENTS §12 stage 1's list — order/shipping/returns/
  price + safety-floor edge cases, Turkish and English) through the real
  pipeline against a synthetic tenant, for manual review.
- ~~Two quality gaps found by the first synthetic run~~ — fixed and
  re-verified against a second full run: (1) intent classification wasn't
  language-stable (a hypothetical pre-purchase return question classified
  as `knowledge_question`/cold in Turkish but `complaint_or_problem`/warm
  in English) — fixed by giving `understand_intent`'s prompt explicit
  per-label definitions, specifically the hypothetical-vs-actual-problem
  distinction that was previously left to the model to infer; both
  languages now return `knowledge_question`/cold. (2) a real
  hallucination — a Turkish price question got told prices are fixed,
  not present in the knowledge base at all, while English correctly
  declined to guess — fixed by strengthening `keep_chatting`'s grounding
  instruction to name prices/policies/guarantees specifically and to
  call out Turkish by name as somewhere not to be less careful; the
  Turkish reply now says it can't state that and a person will confirm,
  matching the English behavior. Both fixes are prompt-only (`app/
  pipeline/graph.py`'s `understand_intent`/`keep_chatting`), no retrieval
  or pipeline-structure changes — re-run the harness again if a similar
  language-asymmetry bug shows up elsewhere, since this class of issue
  isn't proven fixed everywhere, only for these two specific cases.

## 12. Explicitly deferred to later phases

Template gallery, graph-augmented retrieval, embedding/lead-scoring
fine-tuning, multi-user roles beyond "owner," live-data/platform-API
connectors, AI-assisted configuration, the visual flow builder. See
`REQUIREMENTS.md` §10, §13 for the full reasoning on each.

---

*This document plus `REQUIREMENTS.md` together are the reference for
starting Phase 1 development.*
