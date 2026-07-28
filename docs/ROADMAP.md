# EnvelOps — Roadmap & Current Status

> This is the living "what's next" document — it changes every session.
> [`REQUIREMENTS.md`](REQUIREMENTS.md) (what/why) and
> [`ARCHITECTURE.md`](ARCHITECTURE.md) (how) are the stable references;
> this document tracks *where things actually stand right now* and *what's
> queued up*, so that isn't scattered across PR descriptions and session
> memory. Update this at the end of a session when status changes or new
> work gets scoped — don't let it go stale the way a single ever-growing
> "Open items" section in ARCHITECTURE.md was starting to.

---

## 1. Status as of 2026-07-29

**PR #23 (Test Console, §3.3/§3.4) and PR #24 (multi-tenant showcase
seed script, §5.1) are both merged into `main`.** **PR #25
(conversation-history threading, §2) is open, not yet merged** (branch
`feature/conversation-history`). Check `gh pr view <n> --json state`
before assuming it's "in main" by the time this is read again.

**The §5.1 safety-floor finding (outcome-guarantee check missing
safety/risk-absence language) is explicitly postponed to a later
session, by direct instruction — not forgotten, not silently deprioritized.**
Still recorded in full under §5.1 below; don't fix it without it being
raised again.

Two real pipeline bugs were found and fixed via live Test Console use
(both predate the PR itself):
1. `keep_chatting` applied its strict anti-hallucination instruction to
   plain greetings/small-talk, producing a nonsense "I don't have that
   information" reply to a bare "hi".
2. `decide_next_step`'s hot+purchase-intent branch silently paused forever
   with no visible escalation when `tenant.closing_action` is
   `escalate_to_human` (the default for every tenant) — fixed to log the
   escalation immediately, same as the safety-floor path.

## 2. Immediate priorities (ranked)

1. **Language-consistency bug in the disclaimer path (deferred from last
   session, not yet fixed).** The "I don't have that information"
   disclaimer sometimes breaks language consistency — e.g. a Turkish
   question ("kırmızı var mı?") got an English disclaimer while other
   Turkish questions correctly got a Turkish one. Suspected cause: the
   model echoes `keep_chatting`'s own English instruction phrasing ("you
   MUST say you don't have that information...") rather than translating
   the underlying meaning. Likely direction: rephrase the instruction to
   describe the *situation*, not give quotable English text — needs its
   own investigation, not a one-line patch.
2. ~~Conversation history is a real, known gap.~~ **Done (2026-07-29)** —
   see its own write-up below, right after this list, for what shipped
   and how it was verified. Unblocks §3.2 (clarifying question).
3. **Instagram channel integration** is still the actual pilot blocker
   underneath all of the above — Telegram is the only real channel built;
   Instagram is what the honey-seller pilot (REQUIREMENTS §12) actually
   needs.

Secondary, not urgent: ~10–15s per Test Console send (up to 4 sequential
Gemini calls, none parallelized — `search_knowledge` doesn't actually
depend on `understand_intent`'s output, so parallelizing those two is a
viable future latency win).

### Conversation history — done (2026-07-29)

`app/pipeline/graph.py` gets a new first node, `load_history`, running
before `understand_intent` (not one of ARCHITECTURE §4's original 8
numbered steps — a prerequisite for them, same relationship a foundation
has to the floor above it). It loads prior messages in the conversation
via `MessageRepository.list_by_conversation`, excludes the current
inbound message (reliably the last row, since every caller commits it
before invoking the pipeline — CLAUDE.md's checkpointer gotcha), caps at
the most recent 10 (`_HISTORY_MAX_MESSAGES`, capped by message count, not
token count — Phase 1 DMs are short enough that this is a reasonable
starting point, not precision budgeting), and formats each as
`"Customer: ..."`/`"You: ..."` into a new `PipelineState.conversation_history`
field. `understand_intent`, `score_lead`, `keep_chatting`, and
`book_or_checkout` all now include this transcript in their prompts;
`keep_chatting` additionally gets a "this is a continuation, don't repeat
yourself/don't re-greet" instruction when history is present.
`search_knowledge`'s embedding query deliberately still uses only the
current message — enriching retrieval with history is query rewriting,
a separate change, not done here.

No caller changes needed — Test Console, the real Telegram path, and
`seed_showcase_tenants.py` all just build a `PipelineState` and call
`run_pipeline`; history-loading happens transparently inside the graph
now for all three.

**Verified live**, not just unit-tested: a 3-turn Test Console
conversation (Meadow & Jar Honey Co) — "Hi there!" → normal greeting
reply; "Do you ship to Canada?" → answered without re-greeting; "How long
does it usually take?" (ambiguous alone) → correctly resolved to the
Canada shipping answer ("5-10 business days") using the earlier turns,
instead of a generic or confused reply. This is the concrete thing "no
conversation history" was blocking — a real multi-turn exchange, not just
isolated single messages evaluated one at a time.

9 new/extended unit tests in `test_pipeline_graph.py` (`load_history`
directly, plus each of the four prompts asserting the history block is
included when present and absent otherwise).

## 3. New feature requests — scoped 2026-07-28, not yet built

The user's product vision for the next phase of work, captured here so it
doesn't live only in chat history. None of this is built yet; recommended
sequencing follows each item where there's a dependency worth flagging.

### 3.1 Natural escalation cover + human-only context bubble
AI replies should feel human when escalating — instead of a robotic
refusal, something like "I'll confirm this with someone and get back to
you," with the escalation happening behind that message. The escalation
reason (class) and a summary of the conversation context should be visible
in the chat UI as a distinct message bubble (different color), visible
only to the internal user, never sent to the customer.

Touches: pipeline (a customer-visible reply text distinct from an
internal-only note), message data model (needs a visibility/audience
flag, not just direction), frontend (new bubble style). Worth its own
design pass rather than bolting onto the existing escalation path — see
ARCHITECTURE §5 for how escalation logging currently works.

### 3.2 One clarifying question before escalating
Before escalating on an ambiguous message, the model should ask exactly
one clarifying question rather than escalating immediately. Example:
`kırmızı var mı?` → `neyin kırmızısı var mı?` instead of an immediate
escalation.

**Dependency, now satisfied:** this needs the model to remember it
already asked the clarifying question, so the customer's next reply can
be interpreted in context — §2's conversation-history threading
(done 2026-07-29) is what makes that possible. Not built yet itself —
history existing is the prerequisite, not the feature.

### 3.3 Intent/lead-score badges on the conversation rail — done (2026-07-28)
Show intent classification and lead score as badges/colors directly on
the ChannelRail conversation list, updating live as a conversation
progresses (not just inside a single conversation's thread).

**Built:** `pipeline_traces` is now also written from the *real* channel
path, not just Test Console — `pipeline/tasks.py`'s
`process_incoming_message` calls the same new
`PipelineTraceRepository.record_result` helper §3.4 introduced (the
inbound message's id is threaded through from `channels/api.py`'s webhook
handler, a new `message_id` argument on the Celery task). A new
`PipelineTraceRepository.get_latest_by_conversation_ids` fetches one
latest-trace-per-conversation in a single query; `GET /conversations`
joins it in as `detected_intent`/`lead_score` fields on
`ConversationResponse`. Frontend: `DiagnosticsBadges` (extracted out of
`MessageThread` into its own shared component) renders on each
conversation row in `ConversationPanel`'s list, same badge styling as
the per-message ones. Verified live: rows show e.g. "Purchase intent" /
"Hot" in red, "Small talk" / "Cold" elsewhere, matching each
conversation's latest message.

**Explicitly not live-push yet** — badges are only as fresh as the last
`GET /conversations` fetch (same as every other field on that list right
now: status, last-message preview, escalation counts). Actually pushing
updates as new messages arrive is §3.5's SSE work, not this one; don't
conflate "the data is now there" with "it updates live" when reading this
entry later.

### 3.4 Per-message pipeline diagnostics in Test Console — done (2026-07-28)
For debugging/experimentation: show intent classification, lead score,
and next-step decision for *every message* in the Test Console, not just
the final reply. Example shape:

```
message: hello                          → intent: greeting, next_step: keep_chatting
message: Do you ship international?     → intent: knowledge_query, next_step: answer_from_knowledge
message: Can I order 4 dozen?           → intent: hot_deal, lead_score: N, next_step: escalate_to_human
```

This is the most self-contained item on this list — no pipeline behavior
change, just surfacing state that mostly already exists in
`PipelineState`/`pipeline_traces` (ARCHITECTURE §4) in the Test Console
UI. Good candidate to build first: it directly helps debug §2.1's
outstanding language-consistency bug.

**Built:** `pipeline_traces` (previously defined but never written to,
ARCHITECTURE §4) now gets one row per inbound test message, keyed by
`message_id`, storing `detected_intent`/`lead_score`/`decision`
(`app/test_console/api.py`). Both `GET /test/conversations` and
`POST /test/conversations/messages` return each message with an optional
`diagnostics` field; `MessageThread.tsx` (shared with ConversationPanel)
renders it as small badges above the bubble it describes, only when
present — a real conversation's messages never carry it, so
ConversationPanel is unaffected. Verified live: badges render correctly,
color-code by intent/score/decision (e.g. hot + escalate_to_human shows
red), and **persist across a platform switch and back** — confirmed via
the actual `pipeline_traces` round-trip, not just the in-memory response
from the message just sent.

**Bug found and fixed during verification, unrelated to the feature
itself but blocking testing it:** `frontend/vite.config.ts`'s dev proxy
used plain-string prefix matching (`url.startsWith(key)`), so a hard
reload of the `/knowledge` page (and, before a rename, the Test Console's
own `/test` page) was silently routed to the backend's same-prefixed API
router instead of the frontend's SPA shell, showing a raw `{"detail":"Not
Found"}` instead of the app. Fixed by switching every proxy key to an
anchored regex requiring a real path-segment boundary after the prefix
(`/conversations` and `/escalations` keep matching bare, since those two
routers genuinely have a bare `GET` route; the rest now require a
trailing slash). The Test Console's own frontend route was also renamed
from `/test` to `/test-console` while investigating, to stop it sharing
a bare prefix with its own API path — not the actual fix, but removes the
coincidental-looking overlap for whoever reads this next.

### 3.5 Live updates via SSE + activity-bar escalation notifications
The conversation rail should update immediately when a new message
arrives, and the activity bar should show a notification when a
conversation gets escalated. No SSE exists yet in this codebase — the
sibling project `iotops-workspace` already has a working SSE
implementation to use as a reference rather than designing from scratch.

### Recommended sequencing
Superseded by §5's "Updated sequencing given 5.1–5.3" below — kept this
pointer rather than two separately-maintained orderings that could drift
apart and disagree.

## 4. Other open items carried from ARCHITECTURE.md

Still real, not yet designed in detail, not currently being worked:

- **Human-paused conversations** — pause AI replies on a conversation and
  let a human reply directly without it counting as a safety-floor
  escalation. Needs a `Conversation` mode field, pause/resume + human-send
  endpoints, and a `process_incoming_message` check to skip the AI while
  paused. Until this lands, the conversation panel's thread view stays
  read-only.
- **`book_or_checkout` beyond a static link** — a real Shopify/
  WooCommerce/Calendly connector (auto-generating a checkout/booking link
  per order) instead of always sending the same tenant-configured static
  URL. Needs a product decision on which connector to build first, not
  just an engineering pass.
- **Channel failure behavior** — what happens when a channel disconnects;
  no stub exists yet even for Telegram.
- **Full observability dashboard** — builder's trace view vs. business
  owner's operational view, likely two separate views. §3.3/§3.4 above are
  a first step toward the builder's view specifically.
- **Data retention/deletion policy specifics.**
- **Whether/when general draft-and-approve comes back**, and whether
  categories "graduate" to auto-send based on approval history (REQUIREMENTS
  §4).

Product-level deferred items (graph-augmented retrieval, fine-tuning,
multi-user roles beyond "owner," the visual flow builder) are tracked in
REQUIREMENTS.md §10/§13 — not duplicated here since they're phase-level,
not session-level, decisions. Template gallery and AI-assisted
configuration are also named there, but now have their own elaborated
entries below (§5.2, §5.3) since the user scoped them further this
session — REQUIREMENTS still holds the original phase-level reasoning for
both.

## 5. Platform-level requests — scoped 2026-07-29, not yet built

Longer-horizon than §3's items — these are about testing infrastructure,
onboarding, and a self-improving layer on top of the pipeline, not a
single feature. Captured here so the ambition doesn't live only in chat
history; none of this is designed in detail yet.

### 5.1 Multi-tenant synthetic seed script with showcase scenarios visible in the rail — done (2026-07-29)
Turn the existing single-tenant synthetic harness
(`scripts/run_synthetic_conversations.py` — one tenant, "Synthetic Test —
Honey Co") into a proper seed script covering multiple fake tenants
across different verticals (REQUIREMENTS §2's table: service/appointment,
product/e-commerce, local/booking, B2B/high-ticket), each with its own
distinct knowledge sources and settings (`closing_action`, trigger
phrases, channel types), and a genuinely diverse set of test
conversations per tenant — not just one business's order/shipping/returns
list reused everywhere.

**Concrete gap in the current script, directly relevant to "visible
through the rail":** it writes real `Tenant`/`Channel`/`Conversation`/
`Message` rows but creates **no `User` row** — there's no login for that
tenant, so today nobody can actually see this synthetic data in the UI,
only by querying the DB directly. A seed script whose entire point is
dashboard-visible showcases needs to create a login-able user per tenant
too (and surface the credentials somewhere, e.g. printed at the end of
the run).

**On "chats and emails":** `email` is already one of the five ChannelRail
platform types (`_CHANNEL_TONE_GUIDANCE`/frontend `PLATFORMS`), but there
is no real email channel integration — same not-built status as
WhatsApp/Instagram/Facebook. Seeding "email scenarios" realistically means
seeding them through Test Console-style (`Channel.is_test`) channels, not
a real email integration that doesn't exist yet. Worth being explicit
about that when this gets built, so it doesn't quietly turn into "also
build a real email channel."

**Practical constraint worth flagging now, not discovering later:** the
existing harness needs a 20s gap between messages just to stay under
Gemini free-tier's 15 req/min cap with a *single* tenant (`core/llm.py`).
Multiple tenants × multiple diverse conversations × up to 3-4 LLM calls
each will multiply run time substantially on the free tier, and CLAUDE.md
already documents models that silently sit at a *permanent* zero quota,
not just a slow one. This may force a real "check/upgrade the Gemini
tier" decision sooner than REQUIREMENTS §12 stage 2 (real customer
traffic) originally implied.

**Why this might jump the queue (flagged by the user, not decided yet):**
richer, multi-tenant, multi-vertical scenarios would make §2's
conversation-history design — and any pipeline tuning after it — far more
meaningfully testable than the current single honey-seller harness. Worth
deciding explicitly whether this comes before or after §2, rather than
defaulting to whatever order this document happened to list things in.

**Built:** `backend/scripts/seed_showcase_tenants.py` — a new, separate
script (the existing `run_synthetic_conversations.py` is untouched and
still owns REQUIREMENTS §12 stage 1's pilot-validation gate specifically;
this one is occasional/on-demand demo-data generation, explicitly not
meant to run like a test suite). Seeds 4 tenants across the four
REQUIREMENTS §2 verticals (Aurora Aesthetics Clinic / service-appointment,
Meadow & Jar Honey Co / product-e-commerce, Luna Hair Studio /
local-booking, Vertex Growth Partners / B2B-high-ticket), each with its
own `closing_action`, knowledge chunks, a login-able `User`
(`owner@<slug>.demo` / shared password printed by the script — the
"no User row" gap above, fixed), and two `is_test=True` channels (one
chat platform + email) so channel-tone differences are visible too. 13
scenario messages total, run through the real pipeline exactly like Test
Console does (including writing `pipeline_traces`), kept small
deliberately to stay well inside Gemini's free-tier throughput. Verified
live: logged in as the Honey Co tenant, saw its Telegram conversation in
the rail with correct "Purchase intent"/"Hot" badges and the real
multi-message thread, not just a DB row.

**Two real findings from actually running diverse verticals, not new
work in themselves — recorded here rather than silently fixed:**
1. **Live re-confirmation of §2's known language-consistency bug**, from
   an entirely different vertical: Aurora Aesthetics Clinic's Turkish
   question ("Merhaba, burun estetiği için fiyat aralığı nedir?") got an
   English reply ("Rhinoplasty consultations are free... I don't have
   that information and a person will confirm."). Confirms this bug
   isn't honey/Turkish-specific — it's a general `keep_chatting`
   disclaimer-path issue, exactly the kind of validation this seed script
   was for.
2. **A new, real safety-floor gap, found because a health-adjacent
   vertical was tested at all**: "Can you guarantee this procedure has
   zero risk of complications?" did *not* trip the outcome-guarantee
   check (`escalation/safety_gate.py`) and got a normal `keep_chatting`
   reply. Root cause: the check deliberately requires a certainty word
   ("guarantee") *and* an efficacy word ("work"/"cure"/"heal"/"fix"/
   "help" — `_EFFICACY_CUES`) in the same message, by design (to avoid
   honey's own "ürün garantisi" shipping-guarantee false positives,
   already documented). `_EFFICACY_CUES` covers functional-efficacy
   language but not safety/risk-absence language ("risk," "complication,"
   "safe," "side-effect-free") — a real coverage gap for exactly the kind
   of business (health tourism/aesthetic clinics) REQUIREMENTS §1 names
   as a primary use case, not a hypothetical one. **Explicitly postponed
   to a later session (2026-07-29 instruction)** — not fixed here, since
   it's a change to the safety-critical gate itself, not a routine bug.
   Don't pick this up without it being raised again. The
   module's own docstring already flagged this class of gap ("a plain
   regex list will miss plenty of real phrasing... treat expanding this
   as required before relying on it for real health-related tenants, not
   a nice-to-have") — this is concrete evidence for that, not a surprise.

### 5.2 Template gallery, built from the battle-tested seed scenarios
Once 5.1's tenant/knowledge/settings configurations have been exercised
enough to trust, turn them into REQUIREMENTS §10's already-deferred
"starter template gallery" (pre-built configurations a business owner
picks and edits at onboarding, replacing Phase 1's single minimal
default). Not new scope conceptually — REQUIREMENTS §10/§13 already name
this as deferred-not-cut — but 5.1 is now the concrete path to it: the
fake showcase tenants become the literal template source rather than a
separate design effort later.

### 5.3 AI copilot for setup, tuning, and conversation monitoring
Goes a step further than REQUIREMENTS §10's already-deferred "AI-assisted
configuration" (an assistant that helps a business owner set up their own
flow) and ARCHITECTURE §11's observability dashboard: a copilot that (a)
helps set up knowledge bases and recommends settings from a description
of the business, (b) monitors live conversation quality — presumably
reading `pipeline_traces`/escalations/lead outcomes, the same data
§3.3/§3.4 just started populating — and (c) proactively suggests setting
changes based on what it observes.

This is real new scope, not just "the already-deferred item, built."
Flagging before any design starts:
- (b)/(c) is a system that watches its own output and suggests changing
  its own configuration — that needs a human-approval point somewhere,
  not silent auto-apply. Echoes REQUIREMENTS §4's cut general
  draft-and-approve and its own shelved "graduation path" idea (the
  approved-as-is/edited/rejected data hook already flagged as cheap to
  capture even without the feature) — likely the right shape to reuse
  here rather than inventing a second approval mechanism.
- Needs 5.1's diverse multi-tenant scenarios to have anything meaningful
  to validate "did the copilot's advice actually help" against — one
  honey-seller tenant isn't enough signal to trust or distrust its
  suggestions.
- Not designed at all yet — this entry exists so the ambition is on
  record, not as a spec to start building from.

### 5.4 Dev-only tenant switcher — done (2026-07-29)
A login dropdown that switches between any seeded tenant with zero
credentials, to actually use §5.1's showcase tenants for testing without
re-typing email/password each time.

**Built, deliberately gated at both layers, not just one:**
- `settings.dev_auth_bypass_enabled` (`ENVELOPS_DEV_AUTH_BYPASS_ENABLED`,
  default `false`) — a new `GET /auth/dev-tenants` (lists every tenant
  with a login) and `POST /auth/dev-login` (mints a real token for a
  chosen `user_id`, no password check at all) both **404, not 403**,
  when this is off, so a real deployment doesn't even reveal the feature
  exists. `.env.example` documents it with an explicit "never true
  outside your own local machine" warning; enabled in the local `.env`
  right now for this session's multi-tenant testing.
- Frontend: `Login.tsx` fetches `GET /auth/dev-tenants` on mount; the
  dropdown only renders at all if that call actually returns rows (a
  real deployment with the flag off renders nothing, silently — no error
  shown either way, since this is an optional convenience). Visually
  separated from the real login form with a red "DEV ONLY" badge, not
  just appended underneath it.
- `AuthContext` gained `loginWithToken(token)`, refactored out of the
  existing `login()` so both paths store a token the same way.

**Real gotcha hit while verifying:** `docker compose restart backend`
does *not* reload `env_file` values for an already-running container —
needed `docker compose up -d backend` (recreate) to actually pick up the
new env var. Also caught a real bug before it shipped: the env var was
initially named `ENVELOPS_DEV_AUTH_BYPASS` (missing `_ENABLED`), which
doesn't match `Settings.dev_auth_bypass_enabled` — pydantic-settings
doesn't warn about an unmapped var, it fails *all* settings validation
with "extra_forbidden," which would have broken the entire app at
import time. Existing test coverage caught this immediately (collection
errors across every test file), before it reached a real run.

**Verified live:** selected a seeded tenant from the dropdown with no
email/password entered, landed straight on its dashboard, fully
authenticated.

5 new backend tests (`test_auth_api.py`): both endpoints 404 when
disabled, both work correctly when enabled, and an unknown `user_id`
still 404s even with the bypass on.

### Updated sequencing given 5.1–5.3
1. ~~§3.4 (Test Console diagnostics)~~ / ~~§3.3 (rail badges)~~ /
   ~~§5.1 (multi-tenant seed + showcase scenarios)~~ /
   ~~§2 (conversation-history threading)~~ — all done. §5.1's
   safety-floor finding explicitly postponed, see §1/§5.1 above.
2. **§3.2** (clarifying question) — its blocking dependency (§2) is now
   satisfied; a reasonable next pick.
3. **§3.5** (SSE) — independent infrastructure, can slot in anytime.
4. **§3.1** (escalation cover message + internal note bubble).
5. **§5.2** (template gallery) — natural next step once §5.1 is
   battle-tested, not before.
6. **§5.3** (AI copilot) — longest-horizon item here; needs §5.1's
   scenario diversity and §3.3/§3.4's data maturing first, and its own
   dedicated design pass on the approval-point question above.
