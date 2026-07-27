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
`incoming_text`, `detected_intent`, `retrieved_chunks`, `lead_score`,
`decision`, `draft_text`, `escalation_reason` (if any), `escalation_logged`
(§5's double-log guard). This state is what
gets checkpointed at the pause point (§5) and is most of what a
`pipeline_traces` row records — the future observability dashboard can
largely be built by surfacing this object rather than inventing new logging.

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

**Background jobs (Celery):**
- `process_incoming_message` — **built.** Runs the pipeline for one
  message; on `__interrupt__` it commits without replying (the escalation
  was already logged by `decide_next_step` before the pause — see §5);
  otherwise it logs the outbound message and sends it via Telegram,
  catching and logging (not swallowing, not raising) a delivery failure so
  a Telegram outage doesn't lose the Lead/Message rows already written.
- `knowledge_resync` — not built. Manual trigger now, could become
  scheduled later.
- `follow_up_check` — not built. Periodic scan for quiet conversations,
  fires step 8 of the pipeline.
- `channel_health_check` — not built, minimal stub only planned; the real
  "what happens when a channel disconnects" design is still an open item
  (see §11).

## 9. API surface (Phase 1)

`/auth`, `/channels`, `/knowledge`, `/conversations`, `/leads`,
`/escalations`, `/dashboard` — one router per domain module, matching the
`api.py` per module convention.

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

Still empty routers, wired into `main.py` but with nothing behind them:
`/channels` (besides the webhook, §8), `/knowledge`, `/conversations`,
`/leads`, `/dashboard`.

## 10. Frontend screens (Phase 1)

- **Inbox** — conversation list + thread view
- **Escalation queue** — the primary "action needed" screen, since auto-send
  is the default and escalations are the one thing routinely waiting on a
  human
- **Knowledge sources** — add (URL/PDF/manual), list, refresh
- **Settings** — channel connection status; a safety trigger phrase list
  (§5) showing system defaults disabled/locked with an "add your own
  phrase" input — no edit/delete control on defaults, ever
- **Dashboard** — minimal for Phase 1 (leads today, escalations today,
  response times); the full two-audience observability design is still an
  open item (see §11)

No drag-and-drop flow builder in Phase 1.

## 11. Open items carried forward (non-blocking, not designed yet)

- **`book_or_checkout` beyond a static link** — implemented and verified
  with a tenant-configured URL (`Tenant.closing_link`), which is enough for
  any business regardless of platform. A real Shopify/WooCommerce/Calendly
  *connector* (auto-generating a checkout/booking link per order rather
  than sending the same static one) is REQUIREMENTS §13's own step 2
  ("live data connection... for platforms that support it"), not step 1 —
  correctly-sequenced-later work, not a gap, and needs a product decision
  on which connector(s) to build first, not just an engineering pass.
- **Resuming a paused escalation** — the API side is built (`POST
  /escalations/{id}/resolve`, §9, calling `resume_pipeline()`); the
  "Escalation queue" screen (§10) that would actually call it is still
  not built.
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
  pipeline against a synthetic tenant, for manual review. First full run
  surfaced two real gaps, not yet fixed, worth knowing before treating
  REQUIREMENTS §12's synthetic-testing gate as cleared: (1) the same
  question can classify to a different intent/score depending on language
  (a Turkish return question came back `knowledge_question`/cold, the
  English equivalent `complaint_or_problem`/warm — both got the right
  answer, but the classification itself isn't language-stable), and (2) a
  real hallucination — a Turkish price question got told prices are fixed,
  which isn't in the knowledge base at all, while the English equivalent
  correctly declined to guess. Both are prompt/grounding quality issues,
  not pipeline-structure bugs.

## 12. Explicitly deferred to later phases

Template gallery, graph-augmented retrieval, embedding/lead-scoring
fine-tuning, multi-user roles beyond "owner," live-data/platform-API
connectors, AI-assisted configuration, the visual flow builder. See
`REQUIREMENTS.md` §10, §13 for the full reasoning on each.

---

*This document plus `REQUIREMENTS.md` together are the reference for
starting Phase 1 development.*
