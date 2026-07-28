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

## 1. Status as of 2026-07-28

**PR #23 — Test Console** (branch `feature/test-console`) is built and
pushed but **not merged** — the user is deliberately doing a manual testing
pass before merging. Check `gh pr view 23 --json state` before assuming
anything in it is "in main."

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
2. **Conversation history is a real, known gap.** `understand_intent`/
   `score_lead`/`keep_chatting`/`book_or_checkout` only ever see the
   single current `state.incoming_text` — no prior messages, no thread
   context. Every reply is generated in isolation. This blocks item §3.2
   below (a clarifying-question flow needs the model to remember what it
   already asked) and needs its own design pass: how much history, token
   budget, how to thread it through four prompts.
3. **Instagram channel integration** is still the actual pilot blocker
   underneath all of the above — Telegram is the only real channel built;
   Instagram is what the honey-seller pilot (REQUIREMENTS §12) actually
   needs.

Secondary, not urgent: ~10–15s per Test Console send (up to 4 sequential
Gemini calls, none parallelized — `search_knowledge` doesn't actually
depend on `understand_intent`'s output, so parallelizing those two is a
viable future latency win).

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

**Dependency to flag:** this needs the model to remember it already asked
the clarifying question, so the customer's next reply can be interpreted
in context — i.e. it depends on §2's conversation-history gap. Don't build
this ahead of at least minimal history threading, or the model will
re-ask blindly / lose track of its own question.

### 3.3 Intent/lead-score badges on the conversation rail
Show intent classification and lead score as badges/colors directly on
the ChannelRail conversation list, updating live as a conversation
progresses (not just inside a single conversation's thread).

### 3.4 Per-message pipeline diagnostics in Test Console
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

### 3.5 Live updates via SSE + activity-bar escalation notifications
The conversation rail should update immediately when a new message
arrives, and the activity bar should show a notification when a
conversation gets escalated. No SSE exists yet in this codebase — the
sibling project `iotops-workspace` already has a working SSE
implementation to use as a reference rather than designing from scratch.

### Recommended sequencing (proposed, not yet agreed)
1. **§3.4** (Test Console diagnostics) — contained, no behavior change,
   immediately useful for §2.1's outstanding bug.
2. **§3.3** (rail badges) — reuses the same backend fields §3.4 exposes.
3. **§3.5** (SSE) — infra step, unblocks "live" feeling for both of the
   above; crib from iotops-workspace's implementation.
4. **§3.1** (escalation cover message + internal note bubble) — its own
   design pass (message visibility model + pipeline change).
5. **§3.2** (clarifying question) — blocked on §2's conversation-history
   work; do that first or build it alongside.

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

Product-level deferred items (template gallery, graph-augmented retrieval,
fine-tuning, multi-user roles beyond "owner," AI-assisted configuration,
the visual flow builder) are tracked in REQUIREMENTS.md §10/§13 — not
duplicated here since they're phase-level, not session-level, decisions.
