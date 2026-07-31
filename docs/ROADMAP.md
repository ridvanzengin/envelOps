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

## 1. Status as of 2026-07-31

**Portfolio scope pivot — read §6 first, it changes how to read everything
below; §7 is a same-day follow-up on top of it.** The real pilot is
deprioritized; real integrations beyond Telegram (channels and commerce
alike) are cut in favor of simulated ones; Turkish/bilingual pipeline
support is cut, fully now (§7.1 closed the one part §6 originally left
in place). §2's priorities below predate this pivot and are now stale in
places — §6/§7 have the current picture.

**PRs #23–#43 are all merged into `main`.** §8 below covers #39–#43
(safety-floor fix, UI polish, PDF support, knowledge sources redesign) —
check `gh pr view <N> --json state` before trusting this by the time it's
read again regardless. PR #37 (§6's Turkish removal,
real tool-calling + fake connectors, 4 simulated channels, the Settings
Tool-calling tab, and doc housekeeping) merged 2026-07-31. PR #38 (§7's
full Turkish removal + the two calibration-finding fixes) also merged
2026-07-31, same day, as a fresh branch off `main` rather than reusing
PR #37's already-merged branch. Check
`gh pr view <N> --json state` before assuming any PR's status by the time
this is read again, this line goes stale fast (learned the hard way in a
prior session: pushing more commits to an already-merged PR's branch does
NOT bring them into `main` — always verify with `gh pr view`, don't
assume a `git push` succeeding means the changes are live; also learned
the hard way a second time — this exact line sat saying "open, not yet
merged" for a while after the PR had actually merged, until caught and
fixed in the same follow-up session as §7 below).

**The §5.1 safety-floor finding (outcome-guarantee check missing
safety/risk-absence language) was raised again and fixed — see §7.3.**
Was explicitly postponed at the time (2026-07-29), by direct instruction,
until someone raised it again; still recorded in full under §5.1 below
for the original finding/reasoning, not rewritten in place.

Two real pipeline bugs were found and fixed via live Test Console use
(both predate the PR itself):
1. `keep_chatting` applied its strict anti-hallucination instruction to
   plain greetings/small-talk, producing a nonsense "I don't have that
   information" reply to a bare "hi".
2. `decide_next_step`'s hot+purchase-intent branch silently paused forever
   with no visible escalation when `tenant.closing_action` is
   `escalate_to_human` (the default for every tenant) — fixed to log the
   escalation immediately, same as the safety-floor path.

## 2. Immediate priorities (ranked) — **stale as of the §6 pivot, kept for the record**

1. ~~Language-consistency bug in the disclaimer path.~~ **Moot (2026-07-31)**
   — §6's Turkish cut removes the language-matching instruction that
   caused this entirely; there's nothing left to be inconsistent. Resolved
   by cutting the mechanism, not by a targeted fix — see §6 for why.
2. ~~Conversation history is a real, known gap.~~ **Done (2026-07-29)** —
   see its own write-up below, right after this list, for what shipped
   and how it was verified. Unblocked §3.2 (clarifying question).
3. ~~Instagram channel integration is still the actual pilot blocker.~~
   **Superseded (2026-07-31)** — there's no real pilot to unblock anymore
   (§6), and Instagram is now a simulated channel (§6 Milestone 2), not a
   real-integration gap to close.

Secondary, not urgent, still true: ~10–15s per Test Console send (up to 4
sequential Gemini calls even before §6's tool-calling addition, none
parallelized — `search_knowledge` doesn't actually depend on
`understand_intent`'s output, so parallelizing those two is a viable
future latency win).

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

## 3. New feature requests — scoped 2026-07-28

The user's product vision for the next phase of work, captured here so it
doesn't live only in chat history. **All five items (§3.1–§3.5) are now
done** — each has its own "— done (date)" write-up below; this section
header is just the original scoping context, not a current status claim.
Recommended sequencing followed each item where there was a dependency
worth flagging; see §5's "Updated sequencing" for what's left overall.

### 3.1 Natural escalation cover + human-only context bubble — done (2026-07-29)
AI replies should feel human when escalating — instead of silence,
something like "I'll confirm this with someone and get back to you," with
the escalation happening behind that message. The escalation reason
should be visible in the chat UI as a distinct message bubble, visible
only to the internal user, never sent to the customer. Also folded in
during the same pass, at the user's request: relative timestamps on both
the conversation rail and individual messages, and a guarantee that the
escalation note lands as the last message when an escalation happens.

**Data model:** `Message` gets `audience` ("customer" | "internal",
default "customer" — every historical row unaffected) and a nullable
`escalation_id` FK. `Escalation` gets `blocks_pipeline` (bool, default
`True`) — a real bug caught during design review, not obvious going in:
a `pending` `Escalation` doesn't always mean the graph is paused.
`log_lead_and_notify`'s `book_or_checkout`-fallback catch (missing
`closing_link`, a tenant-config issue) creates a `pending` row without
ever pausing the graph, and `layer` can't tell the two cases apart
(both are `"platform_floor"`). Without `blocks_pipeline`, the new
second-message guard below would have frozen a conversation over a
missing checkout link, not just a real safety pause — worse than the bug
being fixed. Only the two real `decide_next_step` interrupt branches
leave it at the `True` default.

**Pipeline:** at each of the three sites that create an `Escalation` row,
`app/pipeline/graph.py` now also generates a natural cover reply
(`_generate_cover_reply`, mirroring `book_or_checkout`'s own existing
holding-reply prompt style, withholding the actual reason) and writes the
internal note directly from the graph node — same established pattern as
the `Escalation`/`Lead` rows themselves, not deferred to the caller.
`_clean_reason_for_display` strips `Escalation.reason`'s own
audit-oriented technical suffix (e.g. the raw regex pattern
`safety_gate.py` names for debugging false positives, the same thing the
user's screenshot showed leaking into the UI) before it becomes the
note's text — `Escalation.reason` itself is untouched, still fully
technical for anyone debugging the safety gate via the API/DB directly.

**Two real bugs found only by running this live, not by unit tests in
isolation:**
1. **A second inbound message on an already-escalated conversation was
   never blocked at all.** Empirically verified by actually running the
   pipeline twice against the same paused thread: `run_pipeline` on an
   already-interrupted `thread_id` doesn't resume or no-op, it silently
   starts a fresh run from the top. New node `check_pending_escalation`
   (right after `load_history`) queries
   `EscalationRepository.get_pending_by_conversation` (filtered to
   `blocks_pipeline=True`) and routes straight to `END` — no LLM calls at
   all — when one is already pending.
2. **Stale checkpoint state leaked through even with that guard in
   place.** First live test: a second message got a full duplicate of
   the *first* message's cover reply, verbatim. Traced (not guessed) via
   a direct script against the real `AsyncPostgresSaver`: LangGraph's
   checkpointer merges a new invocation's input with the *previously
   persisted* channel values for that `thread_id` rather than replacing
   them — so even though `check_pending_escalation` correctly routed to
   `END`, `result` still carried the first run's `draft_text`/`decision`.
   Fixed at the root, not patched per-caller: `check_pending_escalation`
   now explicitly resets `draft_text`/`decision`/`escalation_reason`/
   `escalation_logged` to their defaults whenever it detects a blocking
   pending escalation, so every consumer of the result (message-sending,
   `publish_pipeline_events`, trace recording) sees accurate values
   without each needing its own `already_escalated` special-case. A
   regression test reproduces this exact interaction — two real
   sequential `run_pipeline` calls sharing one `InMemorySaver` thread —
   since the first (mock-seeded, no real prior checkpoint) version of
   this test could not have caught it.
   `PipelineTraceRepository.record_result` is also skipped entirely when
   `already_escalated` — a hollow trace would otherwise blank out a
   previously-good rail badge for that conversation until resolved.

**Message ordering, without a new sequence column:** the cover message
keeps the DB's `server_default=func.now()` (Postgres freezes this at
*transaction start* — the earliest possible value in the transaction).
The internal note explicitly sets `created_at=datetime.now(UTC)` (real
wall-clock, captured after at least one LLM call has already run) —
guaranteeing cover-message-timestamp < internal-note-timestamp regardless
of which is physically inserted first. Accepted tradeoff: relies on the
DB/app server clocks agreeing, fine for Phase 1's single-host
docker-compose deployment.

**Frontend:** the internal note renders in `MessageThread` as a distinct
third participant in the thread — styled like a labeled system/group-chat
message ("Internal note"), not just a recolored version of the customer/
AI bubbles either side of it, per the user's own framing of how it should
read. Reuses the `--danger` tokens already used for the
`escalate_to_human` diagnostics pill rather than introducing a third
accent color. The Resolve button lives inside this bubble, not a
separate top banner (the old `conversation-panel__escalation` block is
gone) — since the note is always the chronologically-last message right
after an escalation, that's already where attention lands, no scrolling
needed. Shown only while `escalationById.get(message.escalation_id)?.status === "pending"`
— an already-resolved note still renders (audit trail) without the
button. `TestConsole.tsx` shares the same `MessageThread` and gets the
note bubble too, but keeps its own existing `escalatedNotice` banner as
the resolve mechanism (it's a debug tool, not a real support queue).

Relative timestamps (`frontend/src/utils/relativeTime.ts`, new
`frontend/src/hooks/useTick.ts` for a 60s live-refresh) on every message
bubble and each conversation-list row, reading `Message.created_at`/
`Conversation.last_message_at` — both already returned by the API, this
was pure frontend rendering work. Deliberately abbreviated units (m/h/d,
falling back to a short date past ~7 days) rather than full sentences —
sidesteps needing i18next plural-form keys entirely, which this codebase
had no precedent for.

**Verified live**, repeatedly, against the real backend (Test Console +
direct API calls) and the real frontend (Playwright): a safety-floor
trigger produced a natural cover reply, then a correctly-ordered internal
note (cleaned reason, right `escalation_id`) as the true last message; a
second message on the same still-pending conversation produced nothing
extra (confirmed empty diagnostics, no new message) only after the two
bugs above were found and fixed — the first live pass caught both;
resolving via the UI's inline button worked, and the very next message
afterward got a normal, fully-decided reply again, confirming the guard
correctly stops blocking once resolved.

15 new/updated backend tests (`test_pipeline_graph.py`'s three escalation
call sites plus a dedicated `TestCheckPendingEscalation`/
`TestCleanReasonForDisplay`, `test_pipeline_runner.py`'s two new
already-escalated tests including the stale-checkpoint regression,
`test_pipeline_tasks.py`'s rewritten interrupted-run test plus a new
already-escalated one) — full suite (174 tests), ruff, and mypy all
clean. No frontend test runner exists in this repo (verified live only,
matching every other UI feature shipped so far).

### 3.2 One clarifying question before escalating — done (2026-07-29)
Before escalating on an ambiguous message, the model should ask exactly
one clarifying question rather than escalating immediately. Example:
`kırmızı var mı?` → `neyin kırmızısı var mı?` instead of an immediate
escalation.

**Dependency, now satisfied:** this needs the model to remember it
already asked the clarifying question, so the customer's next reply can
be interpreted in context — §2's conversation-history threading
(done 2026-07-29) is what makes that possible.

**What "escalating" turned out to mean here, on closer look:** there's no
code path today where an ambiguous *knowledge_question* reaches a real
`Escalation` row — the only two ways `decide_next_step` escalates are the
safety floor and a hot purchase-intent lead (ARCHITECTURE §5). An
ambiguous question was instead falling straight into `keep_chatting`'s
existing disclaimer ("I don't have that information, a person will
confirm") — not a real escalation, just an unhelpful dead end. So the fix
is scoped to `keep_chatting` itself, not `decide_next_step`: no new node,
no new `PipelineState` field, no extra LLM call. The existing single
`keep_chatting` prompt (`app/pipeline/graph.py`) now asks the model to
tell apart three cases, in order: (1) the message is missing a detail
needed to even look the answer up and history doesn't already supply it →
ask exactly one short clarifying question, explicitly not framed as an
escalation; (2) the knowledge base covers it → answer; (3) it's specific
enough but genuinely not in the knowledge base → the original disclaimer.
The "ask exactly one" guarantee comes for free from §2's history
threading — if a clarifying question was already asked last turn, it's
sitting right there in the history block, so the customer's follow-up
lands in branch 2/3 instead of triggering another ask.

**Verified live** (Test Console, Meadow & Jar Honey Co, real Gemini call,
not mocked): "Bunun fiyatı ne kadar?" (no prior context — "this" has no
referent) → correctly asked "Hangi ürünün fiyatını sormuştunuz?" instead
of the disclaimer. Follow-up "Balın 500 gramlık kavanozunu soruyorum" in
the same conversation → did not ask again, correctly fell to the
disclaimer ("Bunun fiyatına sahip değilim...") since no per-size price is
actually in the knowledge base — confirms both the clarifying-question
branch and the ask-only-once mechanism.

**Unrelated gap noticed while testing, not fixed here:** a separate,
non-ambiguous question ("6 tane alırsam indirim var mı?") got the
disclaimer even though the knowledge base does say "discounts for orders
of 6 or more" — looks like a retrieval/grounding miss (the relevant chunk
either wasn't retrieved or wasn't matched to "6 tane" by the model), not
an ambiguity or language-consistency issue. Distinct from both the open
§2.1 language-consistency bug and this section's scope — flagged here
rather than silently ignored or bundled into this fix.

4 new unit tests in `test_pipeline_graph.py` covering the new instruction
branch, that it's absent for small_talk/other, and that a prior clarifying
question surfaces via the history block for the follow-up turn.

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

### 3.5 Live updates via SSE + activity-bar escalation notifications — done (2026-07-29)
The conversation rail should update immediately when a new message
arrives, and the activity bar should show a notification when a
conversation gets escalated. `iotops-workspace`'s own FastAPI +
`sse-starlette` + Redis-pub/sub implementation (`backend/app/event/api.py`)
was the reference pattern, adapted to envelOps's simpler shape: iotops
pattern-subscribes across every project in one connection; here each
authenticated SSE connection already knows its one tenant, so a plain
per-tenant channel subscription (`tenant-events:{tenant_id}`) is enough.

**New dependency:** `sse-starlette` (small, no new transitive deps beyond
`starlette`, which FastAPI already pulls in).

**Backend, new minimal module `app/events/` (no `models.py`/
`repository.py` — no new DB table, same exception `app/test_console/`
already uses for the same reason):** `GET /events/stream` — auth via a
new `get_current_user_from_query` (`app/auth/dependencies.py`), since a
browser's native `EventSource` can't set an `Authorization` header; the
JWT travels as `?token=...` instead, reusing the exact same
`decode_access_token()` the header path already calls. Known, accepted
tradeoff: a token in a URL can end up in server access logs — the
standard workaround every `EventSource`-based app faces, not solved
further here. `app/core/redis_client.py` adds a lazy-singleton async
Redis client (safe only because it's used exclusively inside the FastAPI
process's one long-lived event loop) and `app/core/events.py`'s
`publish_event()` does the actual `PUBLISH`, deliberately swallowing and
logging (never raising) any failure — a live-update push is a nice-to-have
on top of rows every call site has already committed, not something a
Redis blip should be allowed to break message ingestion or the pipeline
run over.

**Real design correction made while implementing, not what was originally
sketched:** the plan going in was to publish directly from inside
`decide_next_step`/`log_lead_and_notify` (`app/pipeline/graph.py`) at each
of the three places an `Escalation` row gets created. That would have
raced a listening frontend's refetch against a not-yet-committed
transaction — those graph nodes run under the *caller's* still-open
session (`app/pipeline/tasks.py`/`app/test_console/api.py` own the
`session.commit()`, not the graph itself, per `PipelineContext`'s own
docstring). Moved instead to a new `publish_pipeline_events(state, result)`
(`app/pipeline/runner.py`), called by each caller *after* its own commit,
interpreting `run_pipeline()`'s already-returned result (the `__interrupt__`
payload for the two interrupt-based escalations, `result["escalation_reason"]`
for `book_or_checkout`'s own missing-`closing_link` fallback — the one
case that sets both an escalation *and* `draft_text` in the same run, so
both events fire together there). Net effect: fewer call sites than
planned (4, not 7) and no race, at the cost of the callers needing to know
this function exists — a straightforward, small tradeoff once the commit-
ordering issue was actually spotted. `_send_follow_up`'s own outbound
message (a periodic job, not a `run_pipeline` call) publishes directly
through `publish_event`, since there's no pipeline result to interpret
there.

**Frontend:** wired directly into the existing `ConversationPanelProvider`
(not a new context) — it already holds `activeChannelType`/
`selectedConversationId` and owns `loadConversations`/`loadEscalations`/
`selectConversation`, which the SSE handler reuses as full re-fetches on
a signal, the same pattern this file already used everywhere else. A
`useRef` snapshot (updated on every render, read inside the `EventSource`
handler) keeps the connection itself keyed only on `token` — it shouldn't
reconnect every time the panel's own open channel/conversation changes.
`vite.config.ts` gained one new anchored proxy key, `^/events(/|\?)`,
following the existing convention.

**Revised after first review, twice, both against a closer read of
`iotops-workspace`'s actual SSE implementation:**

1. **No separate bell/notification UI.** The first pass added a new
   standalone `ActivityBar` component (bell icon + unread badge +
   dropdown). Wrong reference point: `iotops-workspace`'s own
   `ActivityBar.tsx` isn't a bell — it's a persistent icon rail, one icon
   *per project*, each carrying that project's own live unresolved-count
   badge, clicking it opens that project's panel. `ChannelRail` (one icon
   per channel type, each already carrying `pendingEscalationCountByChannelType`'s
   badge, clicking opens that channel's `ConversationPanel`) is already
   envelOps's structural equivalent of that — a second, differently-
   designed bell was a redundant duplicate mechanism, not a missing
   feature. Removed entirely (`ActivityBar.tsx`/`.css`, the `BellIcon`,
   the `activityBar.*` locale keys, and the `liveEscalationNotifications`/
   `dismissNotification` state that only existed to feed it). The
   "escalations shown on platform icons" + "filtered escalations badge on
   each platform's conversation rail" asks were already fully met by
   `ChannelRail`'s existing per-channel badge and `ConversationPanel`'s
   existing "escalated only" filter count (`escalatedCountInList`) — both
   are plain `useMemo`s over the `escalations` array `loadEscalations()`
   already refreshes on every live "escalation" event, so both update
   live for free once that refetch fires. No new UI was actually needed,
   just the live signal feeding data that was already there.
2. **Ground-truth refetch, never a client-side increment.** Directly
   relevant prior art: `iotops-workspace` tried incrementing its
   `ActivityBar` badge counts by +1 per live event first, then abandoned
   that approach (its `EventsContext.tsx` now has its own comment on
   this) because an event doesn't reliably map 1:1 to "the badge should
   go up by exactly one" — resolutions, dedup, and reconnect gaps all
   break that assumption, and the badge quietly drifted from the truth.
   envelOps never had that bug to begin with — `loadEscalations()` always
   does a full `GET /escalations` replacing `escalations` wholesale, and
   `pendingEscalationCountByChannelType`/`escalationByConversationId` are
   both derived from that via `useMemo`, so there's no increment code
   path to have gotten wrong. Called out explicitly in the SSE handler's
   own comment now, specifically so this isn't accidentally reintroduced
   later by someone reaching for the "just increment the badge" shortcut.
3. **Reconnect-refetch was missing — a real gap, not a style choice.**
   `iotops-workspace`'s `EventsContext.tsx` has a `source.onopen` handler
   with its own comment: "closes the Redis Pub/Sub no-buffering gap — a
   message published while nobody was subscribed is simply gone, so this
   is the only way to catch back up after a reconnect." The first pass
   here had no `onopen` handler at all — a dropped connection (network
   blip, backend restart) that `EventSource` silently auto-reconnects
   would have left the rail/badges stuck stale forever, with nothing to
   ever refresh them again short of a full page reload. Added
   `source.onopen` to refetch escalations unconditionally, plus the open
   channel's conversation list and the open thread if either is set —
   mirroring `refetchUnresolvedCounts()`/`refetchOpenPanel()` in the
   reference implementation exactly.
4. **Debounced the per-event refetches.** Also missing from the first
   pass: `iotops-workspace` debounces every SSE-triggered refetch (400ms)
   so a burst of events triggers one request, not one per event. Added
   the same `frontend/src/utils/debounce.ts` (a direct port of iotops's
   own tiny generic utility) and wrapped `loadEscalations`/
   `loadConversations`/`selectConversation` in debounced wrappers for the
   per-event path specifically — the `onopen` resync above stays
   undebounced, matching the reference (it fires rarely enough that
   there's no burst to protect against there).

**Verified live**, not just unit-tested (the actual `/stream` generator
isn't unit-tested either, matching iotops-workspace's own precedent —
streaming generators aren't a good unit-test fit), twice — once before
and once after the corrections above: `curl -N` against `/events/stream`
alongside real Test Console sends showed both a `message` event (inbound
and outbound) and an `escalation` event with the real safety-floor reason
text, in real time. Then the actual frontend, driven in a headless
browser (Playwright, no project skill for this existed yet) against the
real backend: opened the Telegram channel's already-open conversation
panel, sent a message via the API directly (bypassing the UI, simulating
another source), and the new conversation appeared in the list with **no
reload or manual action**. A follow-up safety-floor-triggering message
made `ChannelRail`'s existing Telegram badge count go from 2 to 3, and
`ConversationPanel`'s "escalated only" filter count updated to match —
both **with no reload, no click, and no separate notification UI**. Zero
browser console errors throughout, both passes.

Test coverage: `publish_event` (success + swallowed-failure paths),
`publish_pipeline_events` (all four result shapes: interrupt-based
escalation, `book_or_checkout`'s dual escalation+message case, plain
reply, neither), the `_subscribe` generator (fake pubsub, real filtering/
decoding logic), auth rejection on `/events/stream` (missing/invalid
token), and the message-publish call sites in `channels/api.py`,
`pipeline/tasks.py` (including the follow-up job), and
`test_console/api.py`.

### 3.6 `keep_chatting`'s knowledge-gap disclaimer is now a real escalation, not a dead end — done (2026-07-29)
Found live via Test Console (not scoped in advance, unlike §3.1-3.5): a
`knowledge_question` that's specific enough but genuinely isn't covered
by the knowledge base got told *"I don't have that information and a
person will confirm"* — but nothing was actually notified. No
`Escalation` row, no internal note, no live rail/badge update, no real
human ever pinged. The user's own read on seeing this: *"Knowledge base
do not have that info so escalate the human nothing complicated here"* —
correct, and the fix is exactly that.

**Root cause of why this fell through the cracks:** §3.2's clarifying-
question work explicitly scoped this branch *out* of being a real
escalation ("there's no code path today where an ambiguous
knowledge_question reaches a real Escalation row") — a deliberate choice
at the time, but it left the third branch (question specific enough, but
truly not in the KB) with wording that promises a human follow-up
without any mechanism behind it.

**Fix:** `keep_chatting` (`app/pipeline/graph.py`) now asks the model to
prefix its reply with one status word — `CLARIFY`, `ANSWERED`, or
`NOT_FOUND` — matching which of the three existing branches applies
(parsed via `_KEEP_CHATTING_STATUS_RE`, stripped before the reply ever
reaches the customer; falls back to using the raw text untouched if the
model doesn't follow the format, rather than erroring). On `NOT_FOUND`,
`keep_chatting` (now `async`, takes `runtime: Runtime[PipelineContext]`
like `decide_next_step`) creates a real `Escalation` row
(`layer="knowledge_gap"`, a new value — this is neither the safety floor
nor a business-rule hot-lead call), generates a natural cover reply via
the same `_generate_cover_reply` §3.1 already built (replacing the raw
disclaimer text entirely), and writes the internal note — the same three
pieces every other real escalation site produces. `blocks_pipeline=False`
deliberately, same reasoning as `log_lead_and_notify`'s existing
`book_or_checkout` fallback: the graph already ran to completion, there's
no `interrupt()` pause, so a customer asking something else afterward
shouldn't be frozen over one unanswered question. Reuses
`state.decision`/`escalation_reason`/`escalation_logged` the exact same
way the other escalation sites do, which means `publish_pipeline_events`
(`runner.py`) picks this up as a real "escalation" SSE event for free —
no changes needed anywhere outside `graph.py` for the rail badge to
update live.

**Folded into the same pass, same live-testing session:** `keep_chatting`'s
small-talk/greeting instruction was loose enough ("reply naturally and
conversationally") that a bare "hi" sometimes got personal small talk
back ("hi, how's your day going?") instead of a business assistant
offering help. Reworded to explicitly rule out personal-friend-style
chat and steer toward an offer to help instead.

**Possible side-effect on the open §2 item 1 language-consistency bug,
not confirmed as a full fix:** that bug was specifically about the raw
disclaimer text generated inline in `keep_chatting`'s own big
instruction block. That text no longer reaches the customer at all now
— `_generate_cover_reply`'s already-proven, separately-tested prompt
(§3.1) does, with its own explicit "reply MUST be in this exact same
language" instruction. Spot-checked live with a Turkish knowledge-gap
question ("Çalışma saatleriniz nedir?") and got a correctly Turkish
cover reply ("Bunu hemen ekibe sorup sana birazdan döneceğim!"). Worth
closing §2 item 1 out entirely after broader use, but not claiming that
here from one spot-check.

**Verified live** against the real backend (Test Console API, real
Gemini calls, Meadow & Jar Honey Co): "what are the business hours?" →
`decision` correctly shows `escalate_to_human` (was misleadingly
`keep_chatting`), customer gets a natural cover reply instead of the old
disclaimer, a real `Escalation` row exists (`layer=knowledge_gap`,
`status=pending`) with an internal note bubble carrying the technical
reason; a follow-up message on the same conversation ("do you ship to
Canada?") answered normally, confirming `blocks_pipeline=False` actually
doesn't freeze the conversation; the Turkish equivalent produced a
correctly Turkish cover reply. Greeting fix verified live too: "hello" →
"Hello! How can I help you today?"

Also produced, same session, as the run that surfaced this bug in the
first place: `backend/scripts/run_bitext_stress_test.py`, a new harness
sampling real customer-support phrasing from the public Bitext dataset
(26,872 rows, `backend/data/`, gitignored) across the 14 intents that
map onto a small e-commerce seller's actual knowledge base
(ORDER/CANCEL/SHIPPING/DELIVERY/REFUND/PAYMENT), run through the real
pipeline against a newly-built 26-entry FAQ knowledge base for Meadow &
Jar Honey Co (previously 1-3 placeholder sentences — nowhere near
enough to meaningfully stress-test retrieval). First run (pre-fix): 28
sampled messages, 24 correctly grounded, 4 hit the knowledge-gap
disclaimer — those 4 are exactly the cases this fix now escalates for
real instead of silently dropping.

7 new/updated unit tests in `test_pipeline_graph.py`'s `TestKeepChatting`
(the `NOT_FOUND`-creates-a-real-escalation case including
`layer`/`blocks_pipeline`/internal-note assertions, `ANSWERED`/`CLARIFY`
don't escalate, unparseable-status falls back safely, the small-talk
tone rewording) — full suite (178 tests), ruff, and mypy all clean.

**Hardened same day, real regression caught live within hours of
shipping:** the STATUS-tag approach above relies on the model reliably
prefixing its own reply — not reliable enough on its own. Found via a
real multi-turn Test Console conversation on the **email** channel: its
own tone guidance ("brief greeting... short sign-off") competes with
"your entire response must be exactly this shape: STATUS then your
reply," and the model resolved that conflict by dropping the tag while
still writing the exact disclaimer content verbatim ("Dear Customer,
... we do not have that information, and a person will confirm ...
Best regards, Customer Support") — silently reverting to the pre-fix
dead end this fix was supposed to close, confirmed via direct DB query
(no internal note, no escalation row for that message). Fixed with a
content-based fallback, `_looks_like_not_found_disclaimer` — only
consulted when the STATUS tag is missing, never overrides an explicit
tag, matches the exact English wording the instruction asks for plus a
couple of Turkish equivalents seen in testing. Same layered-detection
principle `escalation/safety_gate.py` already uses, applied here
because a single free-text formatting instruction isn't a strong enough
guarantee for something that decides whether a customer actually gets
escalated.

**Verified live** by reproducing the real failing conversation
end-to-end against the rebuilt backend (multi-turn, email channel,
watches → Rolex → "which models do you have") — the knowledge-gap
turn now correctly produces `decision: escalate_to_human`, a real
`Escalation` row (`layer: knowledge_gap`), and an internal note, where
before it silently fell back to `keep_chatting` with no escalation at
all. 2 more unit tests (`test_untagged_disclaimer_content_still_escalates`,
`test_untagged_answered_text_does_not_falsely_escalate` — the latter
confirming the fallback doesn't false-positive on ordinary replies) —
full suite (180 tests), ruff, mypy all clean.

Also added `.claude/skills/run/SKILL.md` while chasing this down live in
a browser — no `chromium-cli` in this environment, and getting
Playwright actually launching (right `NODE_PATH` into an npx cache dir,
`executablePath` pointing at the one cached Chrome binary whose
revision doesn't need a missing `headless_shell`) cost real time the
first time. Documented so it isn't rediscovered from scratch next
session, per direct instruction after the first pass wasted time on
exactly that.

**Second real behavior bug, same live conversation, flagged directly by
the user: the clarifying-question branch (§3.2) looped three times
asking "which watch / which model / which Rolex model" on a business
that sells honey, instead of recognizing on the very first message that
watches aren't something it has any information about at all.** Root
cause, found by reading `search_knowledge` directly rather than
assuming: `KnowledgeChunkRepository.search_similar` has no relevance
floor — it's a plain `ORDER BY cosine_distance LIMIT k`, so it always
returns the top-K *nearest* chunks regardless of whether any of them
are actually about what's being asked. The model always saw *some*
knowledge block (honey facts) sitting next to a completely unrelated
question and kept treating it as "just needs narrowing down" rather
than "wrong category entirely." Branch 1's instruction now explicitly
requires the knowledge below to already be about the same general
product/topic being asked about before a clarifying question is
appropriate; branch 3 explicitly covers "the knowledge below has
nothing to do with what's being asked at all" as its own trigger,
separate from "specific enough but the fact isn't there." Prompt-only
change — deliberately not the deeper fix (a real similarity/distance
threshold on `search_similar` itself, filtering irrelevant chunks out
of `retrieved_chunks` before they ever reach the prompt), which would
need real calibration against actual retrieval data before trusting a
cutoff value, not a same-session guess.

**Verified live**, reproducing the exact first message from the real
conversation ("hello do you sell watches", email channel, Meadow & Jar
Honey Co): now correctly escalates on the **first message** — `decision:
escalate_to_human`, a real `Escalation` row, natural cover reply — where
before it took three rounds of pointless clarifying questions to get
there. Existing `TestKeepChatting` clarifying-question tests (which use
retrieved_chunks that genuinely are about the same topic being asked,
e.g. "kırmızı var mı?" against `["Available colors: blue, green,
black."]`) still pass unchanged, confirming the legitimate
same-topic-ambiguity case wasn't broken by the tightened wording.

**Third thing checked live, this one *not* a bug:** the user also asked
whether the escalation "successfully" reached the activity/rail badge,
since an earlier test (before the hardening fix above) showed the
disclaimer text but nothing on the badge. Re-verified directly with
Playwright against the rebuilt backend, targeting the **Email** icon
specifically (the real conversation's actual channel, not Telegram):
badge went **1 → 2** live, zero clicks, zero reloads — the earlier
"nothing appeared" report matches exactly what pre-hardening code would
do, since that message never created a real `Escalation` row to begin
with (confirmed via direct DB query at the time). Nothing left to fix
here specifically; recorded so a future report of "badge didn't update"
isn't re-investigated as if it were still open.

**Fourth thing found live, same day, real conversation-quality bug —
"other" intent could echo the customer's own message back verbatim.**
A follow-up multi-turn test ("what time is it?", "where is mahmood?",
"yes the boss" — all genuinely off-topic for a honey seller) surfaced
that `understand_intent`'s `other` label (its own genuine catch-all,
"doesn't fit any of the above") was sharing `small_talk`'s instruction
in `keep_chatting`, which opens with "nothing was actually asked" — a
false premise for a real, if odd, message. That false premise produced
confused output, including two turns where the reply was literally the
customer's own message echoed back unchanged. Gave `other` its own
instruction: acknowledge something was actually said, redirect to how
the business can help, explicit "never repeat or echo the customer's
own message back" guardrail. **Verified live**, reproducing the same
three messages: all three now get a sensible acknowledge-and-redirect
reply ("I am unable to provide information regarding individuals'
locations, but I am happy to assist you with any questions related to
our business offerings...") instead of either a non-responsive
"Hi, how can I help?" or an echo. 1 new/updated unit test in
`test_pipeline_graph.py` (`other` and `small_talk` now assert different
instruction content; a dedicated `other`-intent test checks both the
non-echo guardrail and the absence of the false "nothing was asked"
premise) — full suite (181 tests), ruff, mypy all clean.

**Also worth naming plainly, not just fixing the individual symptoms:**
four real behavior/quality bugs surfaced from live use in this single
session (the knowledge-gap dead end, the dropped-STATUS-tag regression,
the out-of-domain clarify loop, and this echo bug) — all in
`keep_chatting`, the single highest-surface-area node in the pipeline.
Matches the user's own read after seeing this dialogue: the assistant
is meaningfully short of "smooth store assistant" quality yet, not a
one-bug problem. No single further fix closes that gap — it's a
direction for ongoing work, not a checklist item.

### 3.7 Typed, extensible per-tenant AI behavior configuration — done (2026-07-30)
Direct response to §3.6's own closing line: four real behavior bugs in
one session, all from hand-editing prose in `keep_chatting`, was the
signal that ad-hoc prompt-patching had stopped scaling. Discussed at
length with the user first (not started from a spec) — the real
question wasn't "can we add more tenant settings," it was whether an
*abstracted, configurable* AI behavior model is even tractable across
genuinely different domains (health tourism vs. e-commerce vs. B2B) at
all, informed directly by the user's own prior experience: an AI
copilot built for a sibling project (IoTOps) with only 4
deterministic, schema-constrained actions was *already* hard to make
reliably behave. Landed on the actual distinction that makes this
tractable: **bounded policy parameters, not open-ended tenant-authored
instructions.** `closing_action`/trigger-phrases were already proof
this works; the new schema formalizes and extends that pattern rather
than introducing free-text "AI personality" fields, which would
reintroduce the exact competing-instructions failure class §3.6 just
spent three rounds fixing.

**Schema** (`app/tenants/behavior_config.py`, new): `TenantBehaviorConfig`
— `schema_version` + one sub-model per behavior area (`greeting`,
`off_topic`, `knowledge_query`, `complaint`, `lead_handling`,
`escalation_cover`, `book_or_checkout`) plus `channel_overrides`
(per-`channel_type` — "platform" in this project's own UI vocabulary —
tone, the `_CHANNEL_TONE_GUIDANCE` dict's replacement) and a top-level
`general_context` escape hatch. Every model uses `extra="ignore"` (not
pydantic-settings' default `"forbid"`, which CLAUDE.md already
documents breaking the whole app once over one unmapped env var) — the
actual elasticity mechanism: a stored config from an older or newer
schema version deserializes without raising, silently dropping fields
this version doesn't know. Every new value field is `Literal`, a
deliberate break from this codebase's existing "loosely-typed str,
validity enforced by code" convention (`Tenant.closing_action`,
`PipelineState.channel_type`), since this schema's whole purpose is
future dropdown/radio UI introspection. One considered exception:
`channel_overrides` keys stay plain `str`, not `Literal` — Pydantic
validates dict *keys* against a `Literal` regardless of `extra`, so an
unrecognized channel_type would raise on load instead of degrading
gracefully.

**The escape hatch (`additional_context`, per-area + one top-level
`general_context`) is DATA, never behavior** — same shape as
`TenantTriggerPhrase` (a plain fact, appended verbatim, never composed
into new decision logic). Worded in the rendered prompt as "a fact to
be aware of, not an instruction," specifically so it can't quietly
become the free-text-behavior escape valve this whole design exists to
avoid.

**Storage:** one new `Tenant.behavior_config` column (`app/tenants/models.py`),
plain `sa.JSON` (not `postgresql.JSONB` — this column is always read
whole by tenant_id PK lookup, never filtered on its contents; matches
`PipelineTrace.state`, this repo's only other loosely-typed JSON
column). Migration `f556289472b0` — hit the documented checkpoint-table
autogenerate gotcha again (stripped the spurious `DROP TABLE` ops for
`checkpoints`/`checkpoint_migrations`/`checkpoint_writes`/`checkpoint_blobs`
by hand, same as every migration before this one that's hit it).

**Loading:** a new graph node, `load_tenant_config` (`app/pipeline/graph.py`),
wired between `check_pending_escalation` and `understand_intent` —
fetches `Tenant` once per run, stores the *raw dict* on a new
`PipelineState.tenant_behavior_config` field, not the parsed model.
Deliberate: `PipelineState` is checkpointed by LangGraph's Postgres
checkpointer across the `escalate_to_human` pause, and a plain dict is
a proven-safe shape for that; a nested Pydantic model's behavior under
LangGraph's own state serializer across a schema change made between a
pause and its resume was untested risk not worth taking. Every node
needing the typed view calls `load_tenant_behavior_config(...)`
locally — cheap, pure, no I/O.

**Render functions** (`app/pipeline/behavior.py`, new): one per
behavior area, replacing the hardcoded prose that used to live directly
in `graph.py`'s nodes. Hard acceptance bar enforced by test, not just
description: every render function called with an all-defaults config
returns text equal to what the pre-refactor hardcoded string produced
— which is what let `test_pipeline_graph.py`'s entire existing suite
pass **completely unmodified**, the concrete proof this refactor is
behavior-preserving by default. `keep_chatting`'s own decision
mechanism (the `_KEEP_CHATTING_STATUS_RE` parsing, the
`_looks_like_not_found_disclaimer` fallback, NOT_FOUND→escalation
creation — all from §3.6, two live bug fixes deep already) was
deliberately left untouched here; this pass only changes how prompt
*text* is built, never that already-fragile logic, specifically to
avoid compounding risk on it.

**Retrieval threshold, folded in per the user's own call:**
`KnowledgeChunkRepository.search_similar` (`app/knowledge/repository.py`)
gained a real `max_distance` parameter (a cosine_distance ceiling),
`None` by default (today's exact prior behavior — always top-K
regardless of relevance). `KnowledgeQueryConfig.not_found_max_distance`
wires a per-tenant value through `search_knowledge`. This is the actual
root-cause fix for §3.6's out-of-domain clarify-loop bug, now a
tunable instead of a deferred "needs real calibration" problem — the
config model itself *is* the calibration mechanism, no global constant
to guess.

**Deterministic routing, not just tone:** `decide_next_step`'s hot-lead
gate (`lead_score == "hot" and detected_intent == "purchase_intent"`)
now widens to any hot lead when
`LeadHandlingConfig.hot_lead_requires_purchase_intent=False`, and
`closing_action_override` takes precedence over `Tenant.closing_action`
when set (`None` default reproduces today's exact read). Real, code-level
behavior difference, not cosmetic — proven live (see below), not just
asserted.

**Per-vertical starter configs** (`backend/scripts/seed_showcase_tenants.py`):
Aurora Aesthetics Clinic (health-tourism) gets `formal_business` tone
across every area, a tight `not_found_max_distance=0.5` (no guessing
near health claims), and empathetic complaint acknowledgment. Vertex
Growth Partners (B2B, "almost always human-closed" per REQUIREMENTS
§2) gets `formal_business` tone plus
`hot_lead_requires_purchase_intent=False` — the one field demonstrating
genuinely different *deterministic routing* per vertical, not just
tone. Meadow & Jar Honey Co and Luna Hair Studio stay closer to
defaults (`direct_cta` for both, empathetic complaints for Luna) —
low-stakes verticals where the defaults are already the right call.
`run_synthetic_conversations.py`'s tenant stays completely untouched —
never sets this column at all, `{}` default, unaffected — a live proof
of the non-breaking promise, not just an assertion of one.

**Verified live**, not just via the 26 new unit tests: re-updated the
already-seeded Aurora and Vertex tenants' `behavior_config` directly
(the seed script's own re-run isn't idempotent against unique email
constraints — pre-existing limitation, not touched here) and hit them
through the real Test Console API. Aurora: a rhinoplasty recovery
question got a correctly formal, complete-sentence reply ("Typical
recovery involves one to two weeks of visible swelling...") with no
casual contractions. Vertex: a hot-scored `knowledge_question`
("This is time-sensitive: does your team have direct experience
working with fintech companies specifically?" — deliberately not
`purchase_intent`) correctly escalated (`decision: escalate_to_human`)
where the default gate would have kept chatting — the widened
`hot_lead_requires_purchase_intent=False` gate firing for real, not
just in a mock.

26 new tests across four new files (`test_tenant_behavior_config.py`,
`test_pipeline_behavior.py`, `test_knowledge_repository.py` — this
module's first-ever test coverage, an offline statement-compilation
check since this repo has no real-DB repository test precedent to
follow — plus additions to `test_pipeline_graph.py`) — full suite (222
tests), ruff, mypy all clean.

**Explicitly out of scope this pass, by direct instruction:** no
`app/tenants/api.py`, no frontend/settings UI (there's no tenant-config
HTTP API of any kind yet, not even for the pre-existing
`closing_action`/`closing_link`) — a deliberate, separate fast-follow.
No change to `understand_intent`'s fixed 5-label taxonomy or the
graph's fixed node/edge structure beyond the one new `load_tenant_config`
node. No change to `escalation/safety_gate.py`'s own pattern-matching
logic — `EscalationCoverConfig` only touches the cover-reply prose
generated *after* a gate has already fired, never the gate itself.

### 3.8 Tenant settings API + UI — done (2026-07-30)
Direct fast-follow to §3.7's own "explicitly out of scope" line: PR #35
built `TenantBehaviorConfig` but left it entirely script/SQL-only, not
even covering the two pre-existing settings fields (`Tenant.closing_action`,
`closing_link`). Session started from a fully-designed, user-approved
plan written at the end of the §3.7 session specifically so this could
be picked up cold. Went through two real design passes, not one straight
build:

**Pass 1 (single form, full-object save)** — implemented directly against
the carried-over plan: one `GET`/`PUT /tenants/settings`, a combined
`TenantSettingsResponse` model both directions, one long single-column
`Settings.tsx` section with every area stacked top to bottom and one
global Save button. Verified live and working, but the user's own
reaction on seeing it: the single-column layout wasted the page's right-
hand space, and `.form`'s default flex `align-items: stretch` made every
button/input balloon to the full column width once that column was wide
— both real usability problems, not nitpicks, so a second pass followed
immediately rather than shipping pass 1 as-is.

**Pass 2 (two-column, tabbed, independent per-tab save) — the shipped
design**, arrived at through direct back-and-forth with the user rather
than decided solo:
- **Layout**: `Settings.tsx` now renders two columns via a new
  `.settings-columns` CSS grid (`3fr 2fr`, capped `max-width: 1180px`,
  collapsing to one column under 900px) — "AI behavior & business
  settings" (tabbed) on the left, the pre-existing "Safety trigger
  phrases" section unchanged on the right. Splits the page along its
  real seam (behavior config vs. the safety floor are different
  concerns) instead of one long scroll, and both columns now actually
  use the width instead of one narrow stack leaving the rest empty.
- **Tabs**: a new `.tabs`/`.tabs__tab` strip, one tab per behavior area
  plus Closing (10 total: Closing, Greeting, Off-topic, Knowledge,
  Complaints, Leads, Escalation, Booking, Channels, General) — only the
  active tab's fields are mounted, each area's own existing `.title` i18n
  string reused directly as its tab label (no new i18n needed for that
  part). First tab component this app has ever had.
- **Per-tab independent save — the bigger change, from direct user
  feedback mid-build ("instead of just one save button user should be
  able save tabs independently")**: this doesn't work as a frontend-only
  change on top of the full-object `PUT` — sending the whole local
  `settings` object on every tab's save would silently persist whatever
  unsaved edits happened to be sitting in *other* tabs too, which is the
  opposite of independent. Replaced `PUT /tenants/settings` with
  `PATCH /tenants/settings` (`app/tenants/api.py`) taking a new
  `TenantSettingsPatch` — every field optional, but which top-level keys
  were *actually sent* is read from Pydantic's `model_fields_set`, not
  `is not None`, since `closing_link`/`general_context` are meaningfully
  nullable themselves (clearing one is a real, intentional patch, not an
  absent field). Each tab's Save button PATCHes only its own slice — one
  area's full sub-model (`{"greeting": {...}}`), the closing pair
  together, the whole `channel_overrides` dict together, or
  `general_context` alone — server-side merges just that one key into
  the stored `behavior_config` dict, leaving every other area exactly as
  stored. Still zero hand-rolled validation: each patched field is the
  exact same typed sub-model as before (`GreetingConfig`, etc.), so
  `Literal`/`ge`/`le` constraints still 422 automatically.
- **Frontend save state is keyed per tab** (`savingTab: TabKey | null`,
  `saveErrors: Partial<Record<TabKey, string>>`), not one shared flag —
  switching tabs mid-save or after an error on a different tab can't
  bleed a stale spinner/message onto the wrong tab.
- **Button-width fix scoped, not global**: `.form` has no `align-items`
  set (default `stretch`), which is exactly right for `Login.tsx`'s own
  full-width submit button in its narrow 360px card — changing `.form`
  itself would have shrunk that too. Added an opt-in `.button--fit
  { align-self: flex-start }` modifier instead, applied to the tenant-
  settings Save button and the trigger-phrase "Add phrase" button (same
  oversized-bar problem, just not flagged until the two-column pass made
  the column narrower and more obviously wrong), leaving Login untouched.
- Fields within a tab panel use a new `.tenant-settings__fields` grid
  (`repeat(auto-fit, minmax(220px, 1fr))`) instead of one full-width
  column per field, so short controls (dropdowns, checkboxes) sit two-up;
  `.tenant-settings__fields--full` opts a field (additional-context text,
  the closing link, the slider, each channel's own block) back to full
  width.
- Same two new UI primitives from pass 1, unchanged: an editable checkbox
  (the one pre-existing checkbox was disabled/read-only) and an
  `<input type="range">` slider (`knowledge_query.not_found_max_distance`),
  styled via `accent-color: var(--accent)` alone.

**Verified live**, twice — once for pass 1 (full-object save, since
superseded), once for pass 2 against the real rebuilt backend
(`docker compose up -d --build backend worker` to pick up the new PATCH
route) and the real UI (Playwright, headless Chrome for Testing), both
against the already-seeded Aurora Aesthetics Clinic tenant, restoring
Aurora's original showcase config via per-slice PATCHes afterward each
time so neither pass left the documented §5.1 demo tenant altered. Pass
2's own live checks, specifically proving independence (not just that
saving works): edited the Closing tab's dropdown *without saving it*,
switched to Greeting, edited and saved *that* tab — a fresh `GET`
confirmed Greeting's change persisted while Closing's unsaved edit was
correctly discarded, not silently carried along. Reloaded and confirmed
the UI reflected that same server truth. Then saved Closing on its own
tab and confirmed *that* persisted too, with Greeting and the untouched
Knowledge-query area both exactly as they were — independence proven in
both directions, not just asserted. Also confirmed the two-column layout
renders left-to-right as intended and all 10 tabs render. Zero page/
console errors throughout both live passes.

11 backend tests rewritten for `PATCH` semantics in
`test_tenants_api.py` (401/404/defaults-filled GET on empty and partial
stored dicts/patches-closing-pair-only/patches-one-behavior-area-leaving-
others-untouched/patches-channel-overrides-as-one-dict/patches-and-clears-
general_context-to-null/empty-patch-changes-nothing/422 on bad
`closing_action`, out-of-bounds `not_found_max_distance`, and a bad
channel-override literal) — full suite (237 tests), ruff, mypy all clean.
`npm run build`/`npm run lint` clean throughout both passes.

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

## 5. Platform-level requests — scoped 2026-07-29

Longer-horizon than §3's items — these are about testing infrastructure,
onboarding, and a self-improving layer on top of the pipeline, not a
single feature. Captured here so the ambition doesn't live only in chat
history. **Status is mixed, not uniform** — §5.1/§5.4/§5.5 are done (own
write-ups below); §5.2/§5.3 are still not designed in detail, see the
"Updated sequencing" note at the end of this section for what's actually
next.

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
   **Raised again and fixed 2026-07-31 — see §7.3.**

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

### 5.5 Knowledge source + trigger phrase CRUD — done (2026-07-29)
User-flagged gap: knowledge sources and escalation trigger phrases had
create/list (and refresh, for knowledge sources) but no delete.

**Knowledge sources:** a real, undisputed gap — `refresh`'s own error
message for a manual source already said *"delete and re-add instead,"*
which wasn't actually possible since no delete endpoint existed.
`DELETE /knowledge/sources/{id}` now exists, cascading to the source's
chunks via the same `KnowledgeChunkRepository.delete_by_source` refresh
already used.

**Trigger phrases were a different situation, not just a gap** — the
"additive only" design was deliberate (REQUIREMENTS §6): a business
optimizing for fewer escalations could remove an inconvenient phrase,
weakening its own floor, so removal was intentionally left out. Flagged
this explicitly before touching it; **user decided to add delete anyway,
accepting the trade-off** — a permanently-stuck typo'd/mistaken phrase
was judged the worse failure mode. `DELETE /escalations/trigger-phrases/{id}`
now exists. **System defaults are completely unaffected** — still
compiled regex in `safety_gate.py`, not DB rows, no code path touches
them. REQUIREMENTS §6 and ARCHITECTURE §5/§9 updated to reflect the
reversal and why, not left stating the old reasoning as if still current.

Added a generic `TenantScopedRepository.delete()` (`app/core/repository.py`)
rather than one-off delete methods per repository, since both new
endpoints needed the identical get-then-delete shape.

**Checked iotops-workspace's own CRUD conventions before building the
frontend** (`collector/api.py` + `CollectorList.tsx`) — confirms: `204`
on delete, `window.confirm("Delete X? This cannot be undone.")` phrasing,
disabled-while-pending. Two spots kept envelOps's own existing convention
instead of copying iotops exactly, flagged rather than silently
diverging: iotops hides delete behind a "⋮" dropdown (justified there by
3+ actions per row); envelOps's rows only ever have at most two actions,
so delete stays inline next to Refresh. iotops refetches the whole list
after a mutation; envelOps's own established pattern (escalation
resolve, source refresh) is in-place local update, no refetch — kept
that consistent rather than introducing a second sync strategy for just
this one action.

**Verified live:** added then deleted a manual knowledge source (row
count 2→1) and a trigger phrase (visible→gone), both through the real UI
with the confirm dialog accepted.

11 new backend tests across `test_knowledge_api.py`/`test_escalation_api.py`
(401/404/success for both new endpoints).

**Follow-up, same session: "delete" alone wasn't the whole gap.** After
merging the above, the user reported not being able to *see or edit*
knowledge sources at all — seeded ones or ones they'd added themselves.
Checking the API directly (bypassing the browser) confirmed the data was
always there; the actual bug was that the UI never rendered a source's
own content anywhere — the table only ever showed type/source_uri/
chunk_count/last_synced, never what was actually *in* it — and there was
no edit endpoint at all, so the only "correction" path was delete + re-add.

Fixed both, scoped after confirming with the user that URL sources
should stay view-only (their content comes from the URL; refresh already
re-fetches it, so hand-editing would just be silently overwritten):
- `KnowledgeSourceResponse` now includes `content` — the source's chunks
  rejoined with `"\n\n"`. Nothing new stored: `KnowledgeSourceRepository
  .list_with_chunks` (replaces the old `list_with_chunk_counts`) fetches
  each source's chunks directly rather than just a count, two queries
  total regardless of source count, not N+1.
- `PUT /knowledge/sources/{id}` — manual sources only (400 for `url`,
  symmetric with `refresh`'s existing url-only restriction) — replaces
  the source's chunks with newly-chunked/re-embedded text, the same
  delete-then-reingest shape `refresh` already uses.
- Frontend: each row gets a chevron to expand/collapse its content
  read-only, and manual rows additionally get a pencil button that turns
  the same expanded area into a textarea with Save/Cancel.

**Verified live**, twice — once via direct API calls (to isolate
backend vs. frontend before assuming which was broken), once through
the actual browser: expanded a seeded source's content, edited a manual
source's text, saved, and confirmed the new text round-tripped correctly.

5 more backend tests for the new `PUT` endpoint (401/404/400-wrong-type/
400-blank/success).

### Updated sequencing given 5.1–5.3
1. ~~§3.4 (Test Console diagnostics)~~ / ~~§3.3 (rail badges)~~ /
   ~~§5.1 (multi-tenant seed + showcase scenarios)~~ /
   ~~§2 (conversation-history threading)~~ / ~~§3.2 (clarifying
   question)~~ / ~~§3.5 (SSE + activity bar)~~ / ~~§3.1 (escalation cover
   message + internal note bubble)~~ — all done. §5.1's safety-floor
   finding explicitly postponed, see §1/§5.1 above.
2. **§5.2** (template gallery) — natural next step once §5.1 is
   battle-tested, not before.
3. **§5.3** (AI copilot) — longest-horizon item here; needs §5.1's
   scenario diversity and §3.3/§3.4's data maturing first, and its own
   dedicated design pass on the approval-point question above.

## 6. Portfolio scope pivot: simulated integrations, real tool-calling (2026-07-31)

### The decision

Mid-session, while running §5.1's successor (a one-tenant-at-a-time
calibration loop against real Bitext-sampled DMs — see Milestone 4
below), the scope had visibly outgrown what's sustainable for a solo
project: 6-7 planned calibration tenants, a live-commerce-connector
conversation, real multi-channel integration work stacking up. Direct
instruction: re-scope. **The real pilot (a friend's honey business,
REQUIREMENTS §12) is deprioritized — EnvelOps is now explicitly a solo
portfolio project demonstrating AI behavior orchestration/safety/
configuration, not a product being shipped to a real business.** User's
own framing, adopted as the guiding principle for every decision below:
*"this is not an integration project, this is an AI assistant behavior
abstraction showcase project."*

Four concrete decisions followed, each confirmed directly, not assumed:

1. **Turkish/bilingual pipeline support: cut, not deferred.** It was also
   the single biggest recurring bug source this session (language-
   consistency issues found live 3+ separate times) — cutting it resolves
   those bugs by removing the mechanism that caused them, not just less
   scope on paper. REQUIREMENTS §11, ARCHITECTURE §7, CLAUDE.md all
   updated to match (this same housekeeping pass).
2. **Real integrations beyond Telegram: cut in favor of simulated ones**
   — real Instagram/WhatsApp/Facebook Messaging API integrations and a
   real Shopify/WooCommerce commerce connector were both about to pull in
   real credentials, app-review processes, and open-ended external risk
   with no payoff for what this project demonstrates. Simulated instead:
   same real pipeline, webhook-shaped entry points, fake deterministic
   data — see Milestones 1-2.
3. **Multi-tenancy architecture stays; calibration-tenant *count* is
   capped at ~2, not 6-7.** Explicitly not the same decision — ripping
   out working, tested tenant-isolation code for uncertain benefit was
   rejected; the thing actually cut is the *ambition to keep growing
   tenant/vertical breadth*, not the architecture itself.
4. **Tool-calling: real; only the underlying data is fake.** The model
   genuinely decides whether to call a tool (real Gemini function-
   calling); order-status/inventory results come from a stateless,
   hash-seeded fake connector, not a real commerce API.

Also cut in the same conversation, not detailed further here: §5.2
(template gallery) and §5.3 (AI copilot) — both predicated on the
original multi-vertical, many-tenant ambition this pivot explicitly
walked back from.

Three research agents (channel/webhook architecture, LLM tool-calling
readiness, frontend channel representation) plus a design agent produced
a detailed implementation plan before any code was written — see
`/Users/ridvan/.claude/plans/but-i-want-instgram-staged-moon.md` if it's
still around; the milestones below are what actually got built from it,
including two points where live verification changed the plan's own
design (§0.2/§7.3 in that plan file — single tool-decision call instead
of a literal two-turn function-calling loop; calibration stays on Test
Console mechanics rather than routing through the new simulated webhooks).

### Milestone 0 — Turkish removal (done)

Landed first, deliberately, before anything else touched the same
functions. Stripped every "reply in the same language" prompt instruction
out of `app/pipeline/graph.py` (`_generate_cover_reply`, `keep_chatting`,
`book_or_checkout`) and `app/pipeline/behavior.py`
(`render_knowledge_query_instruction`), and dropped the Turkish entries
from `_DISCLAIMER_CONTENT_MARKERS`. **Not touched at the time**: `escalation/
safety_gate.py`'s own Turkish safety-term detection patterns — a
different concern (catching dangerous phrases regardless of language),
still real defensive value. Full backend suite (237 tests at the time)
passed unmodified — nothing asserted the removed strings. **Reversed in a
same-session follow-up — see §7 below**: on direct instruction, those
patterns were removed too, since the project is English-only end to end
now, not English-only-except-one-still-bilingual-safety-module.

### Milestone 1 — Real tool-calling with fake connectors (done)

`app/core/llm.py` gained `generate_with_tools(prompt, tool_declarations)`
— real Gemini function-calling (`types.FunctionDeclaration`/`Tool`/
`GenerateContentConfig`, confirmed against the actually-installed
`google-genai==2.14.0` by constructing real objects, not assumed from
docs; the correct field is `parameters_json_schema`, snake_case, not the
camelCase a first draft used). `tool_config` deliberately left unset
(AUTO) — that default is the actual mechanism that makes "the model
genuinely decides" true.

New `app/commerce/` module (`schemas.py`/`connectors.py`/`tools.py`,
deliberately no `models.py`/`repository.py`/`api.py` — a named exception
to the domain-module convention, since there's no real backing store and
nothing outside the pipeline calls these): `get_order_status`/
`check_inventory`, hash-seeded off the input so the same order number or
product always returns the same fake result — deterministic on purpose,
for reproducible calibration reviews and exact-string tests, not
incidental.

New `ToolCallingConfig` (`app/tenants/behavior_config.py`) — two
independent bounded bools, `order_status_lookup_enabled`/
`inventory_check_enabled`, both `False` by default, following the exact
`not_found_max_distance` precedent (opt-in, off by default, zero extra
Gemini calls until a tenant turns one on).

New `call_tools` node in `app/pipeline/graph.py`, wired onto the
`decide_next_step → keep_chatting` edge only (`call_tools` now sits
between them). Per a user-confirmed design decision: the fake connector's
result is folded into `keep_chatting`'s *existing* knowledge-context
block alongside `retrieved_chunks` — not sent back to Gemini for a second
turn. Cheaper (avoids a 5th/6th sequential free-tier-limited call per
message) and reuses every already-hardened downstream mechanism (STATUS-
tag parsing, knowledge-gap escalation, tone/language rendering) instead
of building a parallel reply path. New `PipelineState.tool_call_results:
list[str]` field, same shape/spirit as `retrieved_chunks`, deliberately
*not* added to `check_pending_escalation`'s reset list (symmetric with
`retrieved_chunks`, which isn't reset either — nothing external reads
either field post-run).

**Verified live against the real Gemini API**, not just mocked: a direct
smoke script confirmed the model calls `order_status_lookup` with the
correct extracted `order_number` for a relevant question, and correctly
declines to call anything for an unrelated one. Later, during Milestone
4's real calibration run, the reply text for a live `track_order`
question ("order 12345 is currently processing... 1 day until delivery")
was checked against calling `get_order_status("12345")` directly — an
exact match — about as close to definitive proof as available that the
real tool-calling path fired in a genuine Gemini-generated reply, not a
mock.

26 new backend tests (`test_commerce.py` — determinism/bounds/dispatch/
formatting; `test_pipeline_graph.py`'s new `TestCallTools` plus a
`TestKeepChatting` addition; one new `test_pipeline_runner.py` test that
actually compiles and runs `build_pipeline_graph()` with `call_tools`
wired in — the only place the edge-mapping change itself gets exercised,
since no `test_pipeline_graph.py` test invokes the compiled graph
directly).

### Milestone 2 — Simulated channels: Instagram, WhatsApp, Facebook, Email (done)

New `app/channels/simulated_client.py` — payload shapes only (`MetaMessagingEvent`
shared by Instagram/Facebook, both genuinely Meta Messenger Platform in
production; `WhatsAppMessage`; `EmailWebhookPayload`), deliberately
flattened one level below each platform's real webhook envelope, not full
fidelity — over-engineering fake payload shapes wasn't the ask.

`app/channels/api.py` extended, not replaced: extracted the logic already
common to every channel's happy path into `_ingest_inbound_message`
(conversation lookup-or-create, message persist, commit, publish_event,
Celery hand-off) and refactored the Telegram handler to call it — a pure
extraction, confirmed safe against the existing Telegram test suite
(patches module-level names that still resolve correctly). Four new
routes (`/channels/{instagram,facebook,whatsapp,email}/{channel_id}/webhook`),
all sharing one `_simulated_webhook` auth/dispatch helper and one uniform
`X-EnvelOps-Simulated-Webhook-Secret` header — deliberately not each
platform's real signature scheme (Meta's HMAC, etc.), which would be
exactly the over-engineering avoided.

**Outbound send needed zero new code** — traced directly against
`app/pipeline/tasks.py`: both send call sites already guard on
`if channel.bot_token:` before attempting a real send, but persist the
outbound `Message` row unconditionally beforehand. A simulated channel
(`bot_token=None`) already gets a fully visible, SSE-published reply with
no real network call, for free.

New `scripts/register_simulated_channel.py` (mirrors
`register_telegram_channel.py` minus the two real-API calls that have no
equivalent) creates the `Channel` row.

**Verified live end-to-end**: a real `curl` POST to
`/channels/instagram/{channel_id}/webhook` flowed through Celery into the
real pipeline and produced a real reply, landing in the DB with
`is_test=False` — confirmed directly via SQL, not inferred.

14 new backend tests (`test_channels_simulated_api.py`) plus the existing
7 Telegram tests re-run unmodified as the refactor's regression check.

### Milestone 3 — Frontend: real vs. simulated labeling (done)

Fixed a real, confirmed 3-way duplication found during research: the
channel-type list existed independently in `ChannelRail.tsx`, `Settings.tsx`,
and `TestConsole.tsx` (the latter two never imported from `ChannelRail`,
and `TestConsole`'s own order didn't even match `ChannelRail`'s). New
`frontend/src/lib/channels.ts` — `CHANNEL_TYPES`, `REAL_CHANNEL_TYPES`,
`isRealChannel()` — is now the one shared source, imported by all three.

`ChannelRail`'s tooltip/CSS class changed from a binary real/"Test only,
not connected yet" framing to real/**Simulated integration** — a
categorically different, more accurate statement now that all five
channels have *something* real behind them (a genuine webhook, even if a
fake one). `.channel-rail__icon--telegram` renamed to
`.channel-rail__icon--real`, applied via `isRealChannel()` instead of a
hardcoded platform check.

`ConversationPanel.tsx` needed **no changes** — `is_test=False` on
simulated channels already makes the existing "Test" pill correctly not
show, exactly as wanted (a simulated-channel conversation reads as a
genuine inbound DM, not a debug session).

**Verified live via Playwright**: Telegram shows "Real integration," the
other four show "Simulated integration," correct tooltip/CSS; the
Instagram conversation created during Milestone 2's live webhook test
rendered in the rail with zero "Test" badges anywhere near it (checked
both by direct DB query and by scoping a Playwright locator to that
specific row, not just a page-wide text search, since "Test console" is
also a nav-link label that would otherwise false-positive a naive check).

`npm run build`/`npm run lint` clean throughout.

### Milestone 4 — Resumed tenant calibration (done, ongoing)

Per a user-confirmed decision: `scripts/seed_calibration_tenant.py` kept
its existing synchronous Test Console mechanics unchanged — simulated
webhooks got their own dedicated tests (Milestone 2) instead of being
routed through the calibration loop itself.

**Tenant #2, Voltage Gadgets** (online consumer electronics, seeded on
the new simulated Instagram channel, both fake tools enabled) appended to
`CALIBRATION_TENANTS` alongside Wildroot Apparel Co (tenant #1, already
calibrated pre-pivot against the pre-tool-calling pipeline). 28 Bitext-
sampled DMs run through the real pipeline. Result: 28/28 sent cleanly, 0
errors — plus tool-calling's own live proof described in Milestone 1.

**Two real findings from this run, not bugs in the new code — pre-existing
pipeline behavior the calibration happened to surface, not yet acted on:**
1. The model fabricates an ungrounded "email support@shop.com" workflow
   for order-modify/cancel requests instead of using the tenant's actual
   knowledge-base policy or escalating — the order-status tool correctly
   declined to fire (it doesn't cover modify/cancel), but the model then
   hallucinated a process rather than falling back correctly.
2. "swap an article of order #12345" (an existing-order request) got
   classified into the `book_or_checkout` branch and sent a fresh
   checkout link — wrong for a modify-existing-order request.

Both flagged to the user, not silently fixed; no decision yet on whether
to address now or later.

### Settings gap-close: Tool calling tab + PATCH support (2026-07-31, same session)

Found via a direct question, not proactively: `ToolCallingConfig`
(Milestone 1) had no UI *and* no way to set it through the real API —
`app/tenants/api.py`'s `TenantSettingsPatch`/`_BEHAVIOR_AREA_FIELDS` were
built in an earlier phase of this same session, before `ToolCallingConfig`
existed, and were never updated. Voltage Gadgets' tool-calling config
only existed because the seed script wrote to the DB directly, bypassing
the API entirely.

Closed both: `tool_calling` added to `TenantSettingsPatch`/
`_BEHAVIOR_AREA_FIELDS` (mechanical — the dispatch loop already handled
any field in that tuple generically), and a new "Tool calling" tab in
Settings.tsx (11th tab now), same pattern as every other tab — two
checkboxes, an additional-context field, plus an explicit "uses simulated
demo data, not a real connected store" notice so it can never read as a
real integration UI.

**Verified live**: toggled Voltage Gadgets' inventory-check checkbox off
through the real UI, saved, confirmed via a fresh `GET` it persisted
through the real `PATCH` endpoint (not just optimistic local state), then
restored it. New backend test (`test_patches_tool_calling`) covering
independence from other areas. 283 backend tests total, ruff/mypy/
`npm run build`/`npm run lint` all clean.

### Status: PR #37 merged

Everything above landed on `feature/simulated-integrations-tool-calling`,
pushed as **PR #37**, merged into `main` 2026-07-31. Docs housekeeping
(this section, plus corrections across CLAUDE.md, REQUIREMENTS.md,
ARCHITECTURE.md) was its own commit on the same branch/PR. §7 below is a
same-day follow-up session, on top of the merge, not part of PR #37 itself.

**§2's "Immediate priorities" above are now stale as of this pivot**:
item 1 (the disclaimer-path language-consistency bug) is moot — resolved
by the Turkish cut, not a targeted fix, there's no language-matching left
to be inconsistent. Item 3 (Instagram integration as "the actual pilot
blocker") no longer applies in its original framing — there's no real
pilot to unblock, and Instagram is now a simulated channel (Milestone 2),
not a real-integration gap. Superseded by this section, not deleted from
§2, so the reasoning that got us here stays visible.

## 7. Same-day follow-up: full Turkish removal + two calibration-finding fixes (2026-07-31)

A follow-up session on top of the merged PR #37, not part of it. Three
pieces of work, all by direct instruction:

### 7.1 `escalation/safety_gate.py`'s Turkish patterns removed too

Milestone 0 above deliberately left `safety_gate.py`'s Turkish
contraindication/symptom/certainty/efficacy patterns in place, reasoning
that pattern-matching dangerous phrases is a different concern from
reply-language-matching. Reversed today, on direct instruction: the
project is English-only end to end now, not
"English-only-except-one-still-bilingual-safety-module." All Turkish
regex alternatives removed from the four pattern lists in
`safety_gate.py` (the module docstring's İ/I-casing caveat and the
"ürün garantisi" false-positive discussion went with them, since both
were Turkish-specific). `tests/test_safety_gate.py`'s
`SafetyFloorTurkishTests` class and the one Turkish tenant-trigger-phrase
test were removed — tenant-added trigger phrases themselves are
untouched (plain substring match, never language-specific to begin
with, so a business owner can still add a non-English phrase if they
want to).

Also scrubbed: the Turkish message variants in
`scripts/run_synthetic_conversations.py`'s `MESSAGES` list (was 16
messages, 8 English + 8 Turkish; now 8, English only) and its docstring;
REQUIREMENTS §11's "Not cut" callout (rewritten — it's cut now); a
same-day addendum in ARCHITECTURE §7. CLAUDE.md's Working-conventions
bullet and test-coverage line updated to match. Deliberately **not**
touched, per direct instruction to keep this backend-only: the frontend's
`react-i18next` UI chrome (`en.json`/`tr.json`, the dashboard's own
language switcher) — inert, isolated, was never the source of any
pipeline problem.

Left alone as unrelated: `scripts/seed_showcase_tenants.py`'s Aurora
Aesthetics Clinic `general_context` line ("operating under Turkish
health-tourism regulations") — that's a factual detail about a fictional
business's setting, not language-support code, no different from any
other real-world detail a demo tenant's flavor text might mention.

### 7.2 Two real calibration findings from Milestone 4, fixed

Both were flagged-not-fixed at the time Milestone 4 landed (see above).
Both are prompt-only fixes.

1. **Hallucinated `email support@shop.com` workflow for order-modify/
   cancel requests.** Root cause: `render_knowledge_query_instruction`
   (`app/pipeline/behavior.py`) framed its three-way CLARIFY/ANSWERED/
   NOT_FOUND decision around "questions," and its NOT_FOUND instruction
   ("say you don't have that information... rather than guessing or
   inferring an answer that merely sounds plausible") wasn't explicit
   enough to stop the model inventing a specific-sounding but ungrounded
   next step for what's really an action *request* (cancel/modify/
   exchange), not an information question — so it never matched the
   NOT_FOUND case, went out as ANSWERED, and the existing
   `_looks_like_not_found_disclaimer` content-based fallback
   (`app/pipeline/graph.py`) couldn't catch it either, since that only
   recognizes the disclaimer's own wording, not a fabricated-but-
   confident answer. Fixed by broadening the instruction to explicitly
   cover "requests to DO something" alongside questions, and adding an
   explicit anti-fabrication line: "Never invent a next step, workflow,
   contact email, phone number, or policy that isn't stated in the
   knowledge below... a confident but made-up answer is worse than
   admitting you don't know." 2 new tests in
   `test_pipeline_behavior.py`'s `TestRenderKnowledgeQueryInstruction`.

2. **"swap an article of order #12345" misrouted into `book_or_checkout`,
   sending a fresh checkout link for what's actually an existing-order
   change.** Root cause: `understand_intent`'s label definitions
   (`app/pipeline/graph.py`) had no concept of "modify/cancel/exchange an
   order the customer already placed" — `purchase_intent` ("ready or
   trying to buy/book right now") was the closest-sounding match, so a
   hot-scored order-change request qualified for the same hot-lead gate
   as a real new sale. Same fix shape as the pre-existing
   hypothetical-vs-actual `knowledge_question`/`complaint_or_problem`
   split (§12 stage 1, already in this prompt): spelled out the boundary
   rather than adding a new label (REQUIREMENTS §3.7 already decided
   against changing the fixed 5-label taxonomy). `knowledge_question`
   now explicitly covers "wanting to modify, cancel, exchange, or track
   an order the customer ALREADY placed"; `purchase_intent` is now
   explicitly scoped to something NEW. Once correctly classified as
   `knowledge_question`, `decide_next_step`'s hot-lead gate no longer
   matches by default (`hot_lead_requires_purchase_intent=True`,
   Voltage Gadgets' actual config, doesn't fire for a non-purchase-intent
   label), so it falls through to `keep_chatting` and gets grounded
   against the tenant's real order-change policy instead — for Voltage
   Gadgets specifically, "Orders can be modified within 30 minutes of
   placing them... only cancelled if not yet shipped," already in its
   knowledge base, previously unreachable because routing never got that
   far. 1 new test in `test_pipeline_graph.py`'s `TestUnderstandIntent`
   asserting the prompt sent to the model contains both boundary
   clarifications.

Full backend suite (278 tests — down from 283: -8 removed Turkish tests,
+3 new ones above), ruff, and mypy all clean.

**Verified live, same day, immediately after merge** — not just
unit-tested: rather than a full 28-message calibration rerun (real
time/quota cost, and unnecessary — only 4 of the 28 originally sampled
messages actually exercised either bug), the exact 4 originally-failing
messages were pulled back out of the DB (`calib-voltage-gadgets-
cancel_order-7`/`-8`, `calib-voltage-gadgets-change_order-3`/`-4`) and
resent fresh through Test Console against the same live Voltage Gadgets
tenant, real Gemini calls, after restarting the `backend`/`worker`
containers to pick up the fix (bind-mounted code, no `--reload`, so a
restart — not a rebuild — was required):

- "canceling purchase #12345" — was a fabricated email-support workflow;
  now correctly escalates (`decision: escalate_to_human`, reason
  `knowledge base has no answer for: ...`), no invented contact info.
- "I want assistance to cancel order #12345" — was the same fabricated
  workflow; now correctly grounded: "Orders can be cancelled if they
  haven't shipped yet, as long as they're past the 30-minute
  modification window."
- "can I update order #12345?" — same fabrication before; now correctly
  grounded on the real 30-minute modify-window fact.
- "swap an article of order #12345" — was misrouted into
  `book_or_checkout` with a fresh checkout link; now `detected_intent:
  knowledge_question` (not `purchase_intent`), `decision: keep_chatting`
  (not `book_or_checkout`), correctly grounded reply citing the same
  real modify/cancel policy — no checkout link sent for an
  existing-order request.

Both fixes hold against real model output, not just the unit tests'
prompt-content assertions. One expected variance worth naming, not a
bug: the two cancellation messages landed on different outcomes
(escalate vs. grounded-answer) despite very similar phrasing — ordinary
retrieval/generation variance across two separate real calls, and both
outcomes are correct (the knowledge base's cancellation fact is
retrievable and answerable; a model choosing to escalate on that same
fact anyway is conservative, not wrong).

### 7.3 §5.1's safety-floor gap fixed (raised again, same day)

The outcome-guarantee check's efficacy-cue list (`_EFFICACY_CUES`,
`escalation/safety_gate.py`) only covered functional-outcome words
("cures", "works", "heals", "fixes", "helps") — a real gap named at
§5.1 and explicitly postponed until raised again, which happened this
session. Note: Aurora Aesthetics Clinic, the tenant that originally
surfaced this gap, no longer exists in the seeded set (tenant count was
capped at ~2 by §6's pivot, and `seed_calibration_tenant.py` never
re-seeded a health-adjacent one) — confirmed live via a direct DB query
before deciding how to proceed. Fixed anyway, unit-tests only, no live
tenant needed: `check_platform_safety_floor` is pure, tenant-independent
platform code, same as every other test in `test_safety_gate.py` already
exercises without a seeded tenant.

Added five new efficacy patterns — `risk`, `complication`, `safe(ty)`,
`dangerous`, `hazard` — alongside the existing functional-outcome ones,
still gated behind the same AND-with-a-certainty-word requirement (a
bare "is it safe?" or "any risk of X?" still doesn't trigger anything on
its own, same false-positive-avoidance shape as the original design).
Module docstring and the `_EFFICACY_CUES` block both updated in place to
explain the two-shape distinction (functional-outcome vs.
risk-absence claims) for whoever reads this next.

**Not live-verified** (unlike §7.2 above) — there's no health-adjacent
tenant currently seeded to exercise this against, and re-seeding one
just to verify a regex change was judged not worth the added scope for
this fix specifically. 4 new unit tests in `SafetyFloorEnglishTests`:
the original motivating phrase ("...zero risk of complications?") now
triggers, a `safe`+`promise` variant also triggers, and two false-
positive checks confirm bare risk/safety language without a certainty
word still doesn't trigger. Full backend suite (281 tests — +4 from
above), ruff, and mypy all clean.

## 8. UI polish + PDF support + knowledge sources redesign (2026-07-31, later same day)

Four more merged PRs, frontend-heavy, each independently branched off
`main` (not stacked): #40 (safety-floor fix, already covered in §7.3
above), #41, #42, #43. Brief pointers, not full write-ups — see each
PR's own description on GitHub for the live-verification detail.

- **#41 — UI polish**: conversation rail badges/filters (Escalated/
  Not-escalated/Hot-lead/Purchase-intent/Complaint, exclusive-select,
  colors shared between filter chip and matching row badge) + client-
  side pagination; Settings redesign (Safety trigger phrases became a
  tab instead of a static column; 12 tabs split into two independent
  groups of 6 shown side by side, each its own nav + card, full page
  width); Test Console toolbar height-matching + editable session name;
  every free-text field (Test Console message box, Settings' additional-
  context fields) converted from `<input>` to resizable `<textarea>`
  with Cmd/Ctrl/Shift+Enter for a newline, plain Enter still submits
  (`utils/submitOnEnter.ts`).
- **#42 — PDF knowledge source support**: closes the one deliberately-
  deferred source type (`docs/ARCHITECTURE.md` §6). New `pypdf`/
  `python-multipart` deps, `POST /knowledge/sources/pdf` (separate
  multipart endpoint), PUT now also accepts pdf for editing.
- **#43 — Knowledge sources page redesign**: full visual/UX overhaul
  from a reference image (stat tiles, pill-style type selector with a
  live "estimated chunks" count that mirrors the backend's real
  `chunk_text()` formula, search/type-filter, card-based rows with a
  kebab menu, per-chunk preview + copy, pagination, "Refresh all").
  Deliberately excluded from the reference: a "Markdown" source type
  (not real backend capability) and a dedicated title field (would need
  a migration — titles are derived from `source_uri`/a content snippet
  instead).

All four verified live via Playwright against the real running stack,
not just built/linted — see each PR description for specifics. Nothing
left mid-flight from this session; next-session candidates are whatever
was already open before it (§4's carried-over items, §5.2/§5.3 if the
portfolio-scope pivot in §6 ever gets revisited) plus, if wanted,
building out the "Markdown" source type PR #43 deliberately skipped.
