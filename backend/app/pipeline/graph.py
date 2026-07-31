"""The fixed 8-step pipeline (docs/ARCHITECTURE.md §4).

Step 1 ("incoming message") happens before this graph runs — the channel
ingestion path (§7) normalizes the message and hands off to Celery, which
builds the initial PipelineState and invokes the graph. The graph's actual
entry point is load_history (docs/ROADMAP.md §2), which runs before step 2
("understand intent") to load prior conversation context; it isn't one of
the original 8 numbered steps, just a prerequisite for step 2 onward
being able to see the rest of the thread. Step 8 (follow-up) is a separate
Celery job that isn't a node in this graph — sending the follow-up itself
is a one-off `generate_text` call (`tasks.py`'s `_send_follow_up`), not a
graph run; a lead's *reply* to that follow-up is just a normal inbound
message, going through the full graph (load_history included) like any
other reply.
"""

import re
import uuid
from datetime import UTC, datetime

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.commerce.tools import enabled_tools, execute, format_result
from app.conversations.models import Message
from app.conversations.repository import MessageRepository
from app.core.llm import embed_text, generate_text, generate_with_tools
from app.escalation.models import Escalation
from app.escalation.repository import EscalationRepository, TenantTriggerPhraseRepository
from app.escalation.safety_gate import check_safety_floor
from app.knowledge.repository import KnowledgeChunkRepository
from app.leads.models import Lead
from app.leads.repository import LeadRepository
from app.pipeline.behavior import (
    render_book_or_checkout_instruction,
    render_channel_tone,
    render_complaint_addendum,
    render_escalation_cover_modifier,
    render_greeting_instruction,
    render_knowledge_query_instruction,
    render_off_topic_instruction,
    render_tool_calling_instruction,
)
from app.pipeline.context import PipelineContext
from app.pipeline.state import PipelineState
from app.tenants.behavior_config import load_tenant_behavior_config
from app.tenants.repository import TenantRepository

_KNOWLEDGE_SEARCH_TOP_K = 5

# Capped by message count, not token count -- Phase 1 DMs are short, and
# precise token budgeting is overkill at this scale (docs/ROADMAP.md §2).
# Revisit if a real tenant's conversations turn out to run long enough for
# this to matter.
_HISTORY_MAX_MESSAGES = 10

# First-pass taxonomy, not a validated product design (REQUIREMENTS.md §2
# says per-business config is deferred) — deliberately generic across all
# four business models in §2's table rather than honey-seller-specific,
# since nothing in the data model yet lets this vary per tenant. Revisit
# once real synthetic/pilot messages (§12) show what's actually missing.
_INTENT_LABELS = frozenset(
    {"knowledge_question", "purchase_intent", "complaint_or_problem", "small_talk", "other"}
)

# keep_chatting's own grounding-vs-natural split -- a greeting or "you
# there?" check-in isn't asking anything, so there's no "answer" to
# ground in the knowledge base at all. Everything else in _INTENT_LABELS
# is treated as a real information request.
_INTENTS_NEEDING_GROUNDING = frozenset(
    {"knowledge_question", "purchase_intent", "complaint_or_problem"}
)

# Parses keep_chatting's own requested "STATUS\n<reply>" response shape
# (only requested when detected_intent needs grounding -- see the prompt
# built there). Matched leniently at the start of the raw response rather
# than requiring an exact two-line shape, since the model won't always
# follow formatting instructions to the letter; group(1) is the keyword,
# match.end() is where the actual customer-facing reply starts.
_KEEP_CHATTING_STATUS_RE = re.compile(
    r"^\s*(CLARIFY|ANSWERED|NOT_FOUND)\b[:\-]?\s*", re.IGNORECASE
)

# Content-based fallback for when the model drops the STATUS tag entirely --
# found live (2026-07-29): the email channel's own tone guidance ("brief
# greeting... short sign-off") competes with "your entire response must be
# exactly this shape: [STATUS] then your reply" and the model resolved that
# conflict by dropping the tag and just writing the greeting/sign-off email
# it's been doing all conversation, landing right back on the pre-fix
# disclaimer text with no escalation created. A required-format instruction
# alone isn't reliable enough for something that decides whether a customer
# gets escalated for real -- this is not exhaustive (matches the exact
# English wording this instruction asks for), but it means a model that
# forgets the tag while still writing disclaimer-shaped prose is still
# caught, same layered-detection spirit as escalation/safety_gate.py.
_DISCLAIMER_CONTENT_MARKERS = (
    "don't have that information",
    "do not have that information",
    "a person will confirm",
)


def _looks_like_not_found_disclaimer(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _DISCLAIMER_CONTENT_MARKERS)

# Also a first-pass default, not tenant-configurable yet (ARCHITECTURE §4:
# "plain LLM call for now"; REQUIREMENTS §2: "what counts as a hot lead"
# must eventually be per-business config). "cold" is the fallback on an
# unrecognized model response, not "warm" — understating a lead's readiness
# is the safer default than overstating it.
_LEAD_SCORES = frozenset({"hot", "warm", "cold"})

# Per-channel_type ("platform") reply tone moved to
# app.pipeline.behavior.render_channel_tone -- was a hardcoded, not-
# tenant-configurable dict here; now the system-default half of that
# render function, with tenant overrides layered on top via
# TenantBehaviorConfig.channel_overrides.


async def load_history(
    state: PipelineState, runtime: Runtime[PipelineContext]
) -> PipelineState:
    """First node in the graph (docs/ROADMAP.md §2) -- loads prior messages
    in this conversation so understand_intent/score_lead/keep_chatting/
    book_or_checkout below aren't generated in total isolation from the
    rest of the thread, the gap flagged after Test Console usage showed
    every reply as a one-off.

    The caller (channel webhook, Test Console, seed scripts) always
    commits the current inbound message before invoking the pipeline
    (CLAUDE.md's checkpointer gotcha), so it's already the most recent row
    here -- excluded from history by dropping the last message, not by
    message id (PipelineState doesn't carry one, and doesn't need to just
    for this).

    Deliberately not used to enrich search_knowledge's embedding query --
    that's query rewriting, a separate, more involved change than
    threading history through the generation/classification prompts
    below; left as a known scoping boundary, not an oversight.
    """
    message_repo = MessageRepository(runtime.context.session)
    messages = await message_repo.list_by_conversation(state.tenant_id, state.conversation_id)
    prior_messages = messages[:-1] if messages else []
    state.conversation_history = [
        f"{'Customer' if message.direction == 'inbound' else 'You'}: {message.text}"
        for message in prior_messages[-_HISTORY_MAX_MESSAGES:]
    ]
    return state


def _history_block(state: PipelineState) -> str:
    if not state.conversation_history:
        return ""
    transcript = "\n".join(state.conversation_history)
    return f"Earlier in this conversation:\n{transcript}\n\n"


async def check_pending_escalation(
    state: PipelineState, runtime: Runtime[PipelineContext]
) -> PipelineState:
    """Second node in the graph, right after load_history (docs/ROADMAP.md
    §3.1) -- closes a real gap found while building the escalation cover-
    message/internal-note feature: run_pipeline() called again on a
    conversation that's already paused at escalate_to_human's interrupt()
    doesn't resume or no-op, it silently starts a brand-new run from the
    top (empirically verified, not assumed). Without this check, a second
    inbound message on an already-escalated conversation could produce a
    second, independent reply or even a second Escalation row, undermining
    the internal note's own "this is the last message" guarantee.

    Only counts *blocking* pending escalations (EscalationRepository.get_
    pending_by_conversation already filters blocks_pipeline=True) --
    book_or_checkout's missing-closing_link fallback creates a pending
    Escalation without ever pausing the graph, and must not freeze a
    conversation over what's just a tenant-config nag.

    Explicitly clears draft_text/decision/escalation_reason/escalation_logged
    below when skipping -- found live, not anticipated: LangGraph's
    checkpointer merges this run's input with the *previously persisted*
    channel values for this thread_id rather than replacing them, so
    without this, `result` would still carry the FIRST run's stale
    draft_text/decision even though nothing was actually decided this
    time -- every caller reading those fields (message-sending,
    publish_pipeline_events) would otherwise act on leftover state from
    the escalation that already happened, not this message.
    """
    escalation_repo = EscalationRepository(runtime.context.session)
    pending = await escalation_repo.get_pending_by_conversation(
        state.tenant_id, state.conversation_id
    )
    state.already_escalated = pending is not None
    if state.already_escalated:
        state.draft_text = None
        state.decision = None
        state.escalation_reason = None
        state.escalation_logged = False
    return state


async def load_tenant_config(
    state: PipelineState, runtime: Runtime[PipelineContext]
) -> PipelineState:
    """Runs once per pipeline invocation, right after check_pending_escalation
    (whose "skip" branch bypasses this node entirely -- an already-
    escalated conversation about to route straight to END never needs
    this fetch either, same "don't do unnecessary work" reasoning as
    that node). Fetches Tenant once and stores its raw behavior_config
    dict on state -- not the parsed TenantBehaviorConfig; see
    PipelineState.tenant_behavior_config's own docstring for why. Every
    node needing the typed view calls
    load_tenant_behavior_config(state.tenant_behavior_config) locally --
    cheap, pure, no I/O, safe to call more than once per run."""
    tenant = await TenantRepository(runtime.context.session).get(state.tenant_id)
    state.tenant_behavior_config = tenant.behavior_config if tenant is not None else {}
    return state


def route_after_escalation_check(state: PipelineState) -> str:
    return "skip" if state.already_escalated else "continue"


def _clean_reason_for_display(reason: str) -> str:
    """Escalation.reason (safety_gate.py) deliberately names the exact
    regex pattern that fired, for audit/tuning purposes -- e.g.
    "contraindication language (matched '\\ballerg(?:y|ic)\\b')". Fine for
    an engineer debugging the safety gate, not for the internal-note
    bubble a business owner reads -- this only affects that display text,
    Escalation.reason itself is untouched. Works generically across every
    current reason format (the plain parenthetical suffix is always where
    the technical detail starts, whether it's "(matched ...)" or
    "(certainty ... + efficacy ...)")."""
    return reason.split(" (", 1)[0].strip()


def _generate_cover_reply(state: PipelineState) -> str:
    """The customer-facing reply sent alongside an escalation (docs/ROADMAP.md
    §3.1) -- mirrors book_or_checkout's own existing missing-closing_link
    fallback prompt style exactly (brief, natural, not apologetic/
    corporate-sounding, holding-reply tone), since that's already a proven
    "we can't actually answer this right now" cover message in this
    codebase. Deliberately withholds the actual reason -- the customer
    gets a natural holding reply, not a safety-floor explanation."""
    behavior_config = load_tenant_behavior_config(state.tenant_behavior_config)
    tone_guidance = render_channel_tone(state.channel_type, behavior_config.channel_overrides)
    cover_modifier = render_escalation_cover_modifier(behavior_config.escalation_cover)
    return generate_text(
        "You are a helpful customer support assistant for a small "
        f"business, replying directly to a customer's message. "
        f"{tone_guidance} This specific question needs a colleague to "
        "weigh in before you can answer it properly -- let them know "
        "briefly and naturally (not robotic, not apologetic-sounding) "
        "that you'll confirm and get back to them shortly. Do not guess "
        "an answer, and do not mention any specific policy, safety, or "
        "eligibility reason.\n\n"
        f"{cover_modifier}"
        f"{_history_block(state)}"
        f"Customer's latest message: {state.incoming_text}"
    )


async def _write_internal_note(
    runtime: Runtime[PipelineContext],
    state: PipelineState,
    escalation_id: uuid.UUID,
    reason: str,
) -> None:
    """Written directly from the graph node under the caller's still-open
    session, same established pattern as Escalation/Lead rows already
    (not deferred to the caller like SSE publishing had to be -- this is
    just another row in the same transaction, no cross-system visibility
    race to worry about). created_at is set explicitly to real wall-clock
    time rather than left on the column's server_default=func.now() --
    Postgres freezes now() at transaction start, so the cover message
    (which keeps the default, frozen at the earliest possible moment)
    always sorts before this note regardless of insertion order. Accepted
    tradeoff: relies on the DB/app server clocks agreeing, fine for
    Phase 1's single-host docker-compose deployment."""
    await MessageRepository(runtime.context.session).add(
        Message(
            tenant_id=state.tenant_id,
            conversation_id=state.conversation_id,
            direction="outbound",
            audience="internal",
            escalation_id=escalation_id,
            text=_clean_reason_for_display(reason),
            created_at=datetime.now(UTC),
        )
    )


def understand_intent(state: PipelineState) -> PipelineState:
    # Explicit per-label definitions, not just the label names -- found via
    # REQUIREMENTS §12 stage 1 synthetic testing: a hypothetical
    # pre-purchase question ("what if I don't like it, can I return it?")
    # was getting classified inconsistently, because nothing told the model
    # where the knowledge_question/complaint_or_problem boundary actually
    # sits. The hypothetical-vs-actual distinction below is what fixes that.
    prompt = (
        "Classify the intent of this customer DM into exactly one of: "
        f"{', '.join(sorted(_INTENT_LABELS))}.\n\n"
        "Label definitions:\n"
        "- knowledge_question: asking for information -- policy, product "
        "details, or a hypothetical \"what if\" scenario about something "
        "that hasn't happened yet (e.g. \"can I return it if I don't like "
        "it?\" is hypothetical, not a real problem, even if phrased with "
        "mild hesitation).\n"
        "- complaint_or_problem: describing an ACTUAL problem with an "
        "order/product the customer already has or experienced (e.g. "
        "\"it arrived damaged\", \"this isn't working\").\n"
        "- purchase_intent: ready or trying to buy/book right now.\n"
        "- small_talk: greeting or chit-chat, no real question.\n"
        "- other: doesn't fit any of the above.\n\n"
        "Respond with just the single label, nothing else, no "
        "punctuation.\n\n"
        f"{_history_block(state)}"
        f"Latest message: {state.incoming_text}"
    )
    raw = generate_text(prompt).strip().lower()
    # The model doesn't always follow the "just the label" instruction
    # perfectly — fall back rather than let arbitrary text flow into
    # state.detected_intent, which later steps will branch on.
    state.detected_intent = raw if raw in _INTENT_LABELS else "other"
    return state


async def search_knowledge(
    state: PipelineState, runtime: Runtime[PipelineContext]
) -> PipelineState:
    behavior_config = load_tenant_behavior_config(state.tenant_behavior_config)
    query_embedding = embed_text(state.incoming_text, task_type="RETRIEVAL_QUERY")
    chunk_repo = KnowledgeChunkRepository(runtime.context.session)
    chunks = await chunk_repo.search_similar(
        state.tenant_id,
        query_embedding,
        limit=_KNOWLEDGE_SEARCH_TOP_K,
        max_distance=behavior_config.knowledge_query.not_found_max_distance,
    )
    state.retrieved_chunks = [chunk.content for chunk in chunks]
    return state


def score_lead(state: PipelineState) -> PipelineState:
    prompt = (
        "Score how ready-to-buy/book this customer is, as exactly one of: "
        "hot, warm, cold. hot = clear purchase/booking intent or urgency; "
        "warm = interested but not decided yet; cold = browsing or a "
        "general question, no buying signal. Consider the whole "
        "conversation so far, not just the latest message — someone who's "
        "asked several questions and now says \"let's do it\" is hotter "
        "than that message would suggest in isolation. Reply with only "
        "the single label, nothing else, no punctuation.\n\n"
        f"{_history_block(state)}"
        f"Latest message: {state.incoming_text}\n"
        f"Detected intent: {state.detected_intent}"
    )
    raw = generate_text(prompt).strip().lower()
    state.lead_score = raw if raw in _LEAD_SCORES else "cold"
    return state


async def decide_next_step(
    state: PipelineState, runtime: Runtime[PipelineContext]
) -> PipelineState:
    phrase_repo = TenantTriggerPhraseRepository(runtime.context.session)
    tenant_phrases = [row.phrase for row in await phrase_repo.list(state.tenant_id)]

    trigger = check_safety_floor(state.incoming_text, tenant_phrases)
    if trigger is not None:
        state.decision = "escalate_to_human"
        state.escalation_reason = trigger.reason
        # Logged here, immediately -- not left until log_lead_and_notify,
        # which only runs after this pauses at escalate_to_human's
        # interrupt() and is later resumed. A human has to be able to SEE
        # the escalation to know to resume it in the first place, so
        # logging it can't wait for a step that only runs once someone's
        # already acted on it.
        escalation_repo = EscalationRepository(runtime.context.session)
        created = await escalation_repo.add(
            Escalation(
                tenant_id=state.tenant_id,
                conversation_id=state.conversation_id,
                reason=trigger.reason,
                layer=trigger.layer,
                status="pending",
            )
        )
        # Tells log_lead_and_notify this one's already recorded, so
        # resuming past the pause (POST /escalations/{id}/resolve) doesn't
        # log it a second time.
        state.escalation_logged = True
        # docs/ROADMAP.md §3.1 -- a natural cover reply instead of silence,
        # plus an internal-only note explaining why, written directly here
        # (same pattern as the Escalation row above), both before the
        # pause below actually happens (escalate_to_human's interrupt()).
        state.draft_text = _generate_cover_reply(state)
        await _write_internal_note(runtime, state, created.id, trigger.reason)
        return state

    # Past the safety floor: auto-send is the Phase 1 default (ARCHITECTURE
    # §5), so anything short of a hot, clearly-buying lead just keeps
    # chatting rather than escalating on a hunch — there's no general
    # "when in doubt, ask a human" rule here, only the safety floor above.
    # hot_lead_requires_purchase_intent=False (LeadHandlingConfig) widens
    # this gate to any hot lead regardless of intent label -- real,
    # deterministic routing, e.g. Vertex Growth Partners (B2B, "almost
    # always human-closed" per REQUIREMENTS §2) wants a hot lead routed
    # toward closing even if it arrived as a knowledge_question.
    behavior_config = load_tenant_behavior_config(state.tenant_behavior_config)
    lead_handling = behavior_config.lead_handling
    intent_matches_hot_lead = (
        state.detected_intent == "purchase_intent"
        or not lead_handling.hot_lead_requires_purchase_intent
    )
    if state.lead_score == "hot" and intent_matches_hot_lead:
        tenant_repo = TenantRepository(runtime.context.session)
        tenant = await tenant_repo.get(state.tenant_id)
        # A missing tenant row shouldn't be possible in practice (state.tenant_id
        # comes from an already-authenticated context), but if it somehow
        # happened, defaulting to auto-send here would be exactly backwards.
        # closing_action_override (LeadHandlingConfig), when set, takes
        # precedence over Tenant.closing_action -- a dormant, opt-in seam;
        # None (the default) reproduces today's exact tenant.closing_action
        # read.
        state.decision = (
            lead_handling.closing_action_override
            or (tenant.closing_action if tenant is not None else None)
            or "escalate_to_human"
        )
        if state.decision == "escalate_to_human":
            # Real bug, found via Test Console (not synthetic testing --
            # the synthetic tenant always sets closing_action=
            # book_or_checkout, so this path never ran there): this is a
            # SECOND way decision can become "escalate_to_human", besides
            # the safety-floor branch above, and it used to fall straight
            # through to escalate_to_human's interrupt() without ever
            # setting escalation_reason or logging an Escalation row --
            # since closing_action defaults to escalate_to_human for
            # every tenant that hasn't opted into book_or_checkout
            # (Tenant.closing_action's own docstring), this was silently
            # dropping every hot purchase-intent message for the *default*
            # tenant config: pipeline pauses, no reply, no Escalation row
            # for a human to ever see or resolve. Same
            # log-immediately-before-the-pause reasoning as the
            # safety-floor branch above -- log_lead_and_notify never runs
            # until this is resumed, so waiting for it isn't an option.
            state.escalation_reason = (
                "hot purchase-intent lead (tenant closing_action is escalate_to_human)"
            )
            escalation_repo = EscalationRepository(runtime.context.session)
            created = await escalation_repo.add(
                Escalation(
                    tenant_id=state.tenant_id,
                    conversation_id=state.conversation_id,
                    reason=state.escalation_reason,
                    layer="business_rule",
                    status="pending",
                )
            )
            state.escalation_logged = True
            state.draft_text = _generate_cover_reply(state)
            await _write_internal_note(runtime, state, created.id, state.escalation_reason)
        return state

    state.decision = "keep_chatting"
    return state


def route_after_decision(state: PipelineState) -> str:
    """Reads state.decision (set by decide_next_step) to pick a branch."""
    if state.decision is None:
        raise ValueError("decide_next_step must set state.decision before routing")
    return state.decision


def call_tools(state: PipelineState) -> PipelineState:
    """Runs on the decide_next_step -> keep_chatting edge only (never on
    the escalation/book_or_checkout branches, which don't need live data
    for a holding reply or a checkout handoff). Sync/DB-free, same shape
    as understand_intent/score_lead. Fully inert -- zero extra Gemini
    calls -- for every tenant that hasn't opted into a fake connector
    (app/tenants/behavior_config.py's ToolCallingConfig), which is every
    tenant today.

    Deliberately a single decision call, not a two-turn function-calling
    loop: the fake connector's result is folded into keep_chatting's own
    existing prompt (see its context_block below) rather than sent back to
    Gemini for a second turn, to avoid a second sequential Gemini call per
    tool-using message and to keep keep_chatting's already-hardened
    STATUS-tag/escalation logic completely untouched."""
    if state.detected_intent not in _INTENTS_NEEDING_GROUNDING:
        return state
    behavior_config = load_tenant_behavior_config(state.tenant_behavior_config)
    declarations = enabled_tools(behavior_config.tool_calling)
    if not declarations:
        return state

    prompt = (
        "You can call a tool to look up a real order's status or a "
        "product's inventory, if the customer's message actually needs "
        "one. Only call a tool when you can confidently extract the "
        "information it needs (e.g. an order number) from the message or "
        "conversation below -- if you don't have enough to call it "
        "confidently, don't call it and don't guess a value.\n\n"
        f"{render_tool_calling_instruction(behavior_config.tool_calling)}"
        f"{_history_block(state)}"
        f"Latest message: {state.incoming_text}"
    )
    _text, tool_calls = generate_with_tools(prompt, declarations)

    results = []
    for call in tool_calls:
        result = execute(call.name, call.args)
        if result is not None:
            results.append(format_result(call.name, result))
    state.tool_call_results = results
    return state


async def keep_chatting(
    state: PipelineState, runtime: Runtime[PipelineContext]
) -> PipelineState:
    behavior_config = load_tenant_behavior_config(state.tenant_behavior_config)
    tone_guidance = render_channel_tone(state.channel_type, behavior_config.channel_overrides)

    # Found via real Test Console usage (not synthetic testing -- REQUIREMENTS
    # §12's fixed message list never included a bare greeting/check-in): the
    # strict grounding instruction below used to apply unconditionally, so a
    # plain "merhaba"/"you there?" -- small_talk, not a real question --
    # still got the "I don't have that information" disclaimer, since there
    # was nothing in the knowledge base about greetings either. Only
    # information-seeking intents actually need the "don't guess" rule; a
    # greeting just needs a greeting back.
    #
    # The clarifying-question branch (docs/ROADMAP.md §3.2) inside
    # render_knowledge_query_instruction (app/pipeline/behavior.py) is
    # checked FIRST, before the disclaimer -- an ambiguous question
    # ("kırmızı var mı?" with no product named) isn't "missing from the
    # knowledge base," it's missing a detail needed to even look it up.
    # That instruction also explicitly requires the knowledge below to
    # already be about the same general topic -- found live (2026-07-29):
    # search_knowledge (KnowledgeChunkRepository.search_similar) had no
    # relevance floor, so the model saw *some* knowledge block next to an
    # entirely unrelated question ("do you sell watches?") and kept
    # asking which specific watch/model/brand across three turns instead
    # of recognizing the whole category wasn't covered at all -- fixed at
    # the root now via KnowledgeQueryConfig.not_found_max_distance
    # (search_knowledge), this instruction wording is the second layer.
    if state.detected_intent in _INTENTS_NEEDING_GROUNDING:
        # tool_call_results (call_tools, right before this node) folds in
        # here alongside retrieved_chunks -- same context block, so the
        # CLARIFY/ANSWERED/NOT_FOUND mechanism below never needs to know
        # whether a given fact came from the knowledge base or a fake
        # live-data tool call.
        context_lines = [f"- {chunk}" for chunk in state.retrieved_chunks] + [
            f"- {result}" for result in state.tool_call_results
        ]
        context_block = (
            "\n".join(context_lines)
            if context_lines
            else "(no matching knowledge found for this question)"
        )
        content_instruction = render_knowledge_query_instruction(
            behavior_config.knowledge_query, context_block
        )
        if state.detected_intent == "complaint_or_problem":
            content_instruction = (
                render_complaint_addendum(behavior_config.complaint) + content_instruction
            )
    elif state.detected_intent == "small_talk":
        content_instruction = render_greeting_instruction(behavior_config.greeting)
    else:
        # "other" is understand_intent's genuine catch-all ("doesn't fit
        # any of the above") -- found live (2026-07-29): this used to
        # share small_talk's instruction, which falsely claims "nothing
        # was actually asked." For something like "where is mahmood?" or
        # "yes the boss" -- a real message, just not a business question,
        # complaint, or purchase interest -- that false premise produced
        # a confused reply, up to and including literally echoing the
        # customer's own message back verbatim. render_off_topic_instruction
        # gets its own wording: acknowledge something was actually said,
        # don't pretend otherwise, and explicitly rule out parroting it back.
        content_instruction = render_off_topic_instruction(behavior_config.off_topic)

    history_block = _history_block(state)
    # Only relevant once there's actually a prior turn to not repeat --
    # an empty instruction here for a conversation's first message, same
    # behavior as before conversation_history existed.
    continuation_instruction = (
        "This is a continuation of an ongoing conversation -- don't repeat "
        "information you've already given, and don't greet them again "
        "since you already have.\n\n"
        if history_block
        else ""
    )

    prompt = (
        "You are a helpful customer support assistant for a small business, "
        f"replying directly to a customer's message. {tone_guidance}\n\n"
        f"{content_instruction}"
        f"{history_block}"
        f"{continuation_instruction}"
        f"Customer's latest message: {state.incoming_text}"
    )
    raw = generate_text(prompt).strip()

    needs_grounding = state.detected_intent in _INTENTS_NEEDING_GROUNDING
    status_match = _KEEP_CHATTING_STATUS_RE.match(raw) if needs_grounding else None
    state.draft_text = raw[status_match.end() :].strip() if status_match else raw

    # Real escalation, not a dead end -- found live (2026-07-29): this
    # branch previously just told the customer "a person will confirm"
    # without ever actually notifying anyone or creating an Escalation
    # row, unlike the other two decide_next_step escalation sites. Same
    # non-blocking shape as log_lead_and_notify's book_or_checkout
    # fallback below (blocks_pipeline=False -- the graph already ran to
    # completion, no interrupt() pause, so a customer asking something
    # else afterward shouldn't be frozen over one unanswered question),
    # reusing state.decision/escalation_reason/escalation_logged the same
    # way so publish_pipeline_events (runner.py) picks this up as a real
    # "escalation" SSE event for free, no caller-side changes needed.
    #
    # is_not_found doesn't just trust status_match -- found live the same
    # day this shipped: the email channel's tone guidance ("brief
    # greeting... short sign-off") competes with the STATUS-tag
    # instruction, and the model dropped the tag while still writing the
    # exact disclaimer content, silently reverting to the pre-fix dead
    # end. _looks_like_not_found_disclaimer is the fallback net for
    # exactly that case -- only consulted when the tag is missing, never
    # overrides an explicit CLARIFY/ANSWERED tag.
    tagged_not_found = (
        status_match is not None and status_match.group(1).upper() == "NOT_FOUND"
    )
    untagged_but_looks_like_it = (
        status_match is None and needs_grounding and _looks_like_not_found_disclaimer(raw)
    )
    is_not_found = tagged_not_found or untagged_but_looks_like_it
    if is_not_found:
        state.escalation_reason = f"knowledge base has no answer for: {state.incoming_text!r}"
        state.decision = "escalate_to_human"
        state.escalation_logged = True
        escalation_repo = EscalationRepository(runtime.context.session)
        created = await escalation_repo.add(
            Escalation(
                tenant_id=state.tenant_id,
                conversation_id=state.conversation_id,
                reason=state.escalation_reason,
                layer="knowledge_gap",
                status="pending",
                blocks_pipeline=False,
            )
        )
        state.draft_text = _generate_cover_reply(state)
        await _write_internal_note(runtime, state, created.id, state.escalation_reason)

    return state


def escalate_to_human(state: PipelineState) -> PipelineState:
    """The safety-gate pause point (§5, §6) — the only pause in Phase 1.
    Compiling this graph with a checkpointer (Postgres-backed, see
    app/pipeline/runner.py) and calling `interrupt()` here is what makes
    the pause/resume durable; that wiring lives wherever the graph is
    compiled and invoked, not in this module. Calling this function
    directly, outside a graph run with a checkpointer attached, doesn't
    pause anything — interrupt() needs the graph engine's execution
    context to mean anything."""
    interrupt(
        {
            "conversation_id": str(state.conversation_id),
            "incoming_text": state.incoming_text,
            "escalation_reason": state.escalation_reason,
        }
    )
    return state


async def book_or_checkout(
    state: PipelineState, runtime: Runtime[PipelineContext]
) -> PipelineState:
    tenant_repo = TenantRepository(runtime.context.session)
    tenant = await tenant_repo.get(state.tenant_id)
    closing_link = tenant.closing_link if tenant is not None else None

    if not closing_link:
        # A real operational gap (tenant set closing_action=book_or_checkout
        # but never configured a link), not a code bug. Setting
        # decision=escalate_to_human here does NOT pause the conversation
        # the way a real safety-floor escalation does -- routing already
        # happened at decide_next_step's conditional edge, so this node
        # still proceeds straight to log_lead_and_notify next, not to
        # escalate_to_human's interrupt(). What it does do: makes
        # log_lead_and_notify (which reads state.decision fresh) log this
        # as a real Escalation row for the business owner to notice and
        # fix, while still auto-sending the customer an honest holding
        # reply instead of leaving them hanging over what's just a config
        # issue, not a safety one -- deliberately different tradeoff than
        # the safety floor, which must never auto-send.
        behavior_config = load_tenant_behavior_config(state.tenant_behavior_config)
        tone_guidance = render_channel_tone(
            state.channel_type, behavior_config.channel_overrides
        )
        state.decision = "escalate_to_human"
        state.escalation_reason = "book_or_checkout: tenant has no closing_link configured"
        state.draft_text = generate_text(
            "You are a helpful customer support assistant for a small "
            f"business, replying directly to a customer's message. "
            f"{tone_guidance} The customer wants to buy/book right now but "
            "you don't have a direct link to send them — let them know "
            "briefly (not apologetic or corporate-sounding) that someone "
            "from the team will follow up shortly to complete this.\n\n"
            f"{_history_block(state)}"
            f"Customer's latest message: {state.incoming_text}"
        )
        return state

    behavior_config = load_tenant_behavior_config(state.tenant_behavior_config)
    tone_guidance = render_channel_tone(state.channel_type, behavior_config.channel_overrides)
    cta_instruction = render_book_or_checkout_instruction(
        behavior_config.book_or_checkout, closing_link
    )
    prompt = (
        "You are a helpful customer support assistant for a small business, "
        f"replying directly to a customer's message. {tone_guidance} "
        f"{cta_instruction}\n\n"
        f"{_history_block(state)}"
        f"Customer's latest message: {state.incoming_text}"
    )
    state.draft_text = generate_text(prompt)
    return state


async def log_lead_and_notify(
    state: PipelineState, runtime: Runtime[PipelineContext]
) -> PipelineState:
    """Step 7 (REQUIREMENTS §3): "recorded, tagged with source." Only the
    "log" half is built — "notify team" has no channel designed yet
    (ARCHITECTURE §10, still an open item), so this silently skips it
    rather than fake a notification that doesn't go anywhere. "Tagged with
    source" doesn't need a field here: conversation_id already links to
    the conversation's channel.

    Doesn't call session.commit() — that's the caller's job (whoever
    invokes graph.ainvoke() owns the session for the whole run, per
    PipelineContext's docstring), same as every other DB-touching node
    here. Repository.add() already flushes, which is enough for
    within-transaction visibility.
    """
    lead_repo = LeadRepository(runtime.context.session)
    await lead_repo.add(
        Lead(
            tenant_id=state.tenant_id,
            conversation_id=state.conversation_id,
            score=state.lead_score or "cold",
            notes=state.detected_intent,
        )
    )

    if (
        state.decision == "escalate_to_human"
        and state.escalation_reason is not None
        and not state.escalation_logged
    ):
        # blocks_pipeline=False -- this is the book_or_checkout missing-
        # closing_link fallback, the only path that reaches this branch
        # (both real safety-gate escalations already set escalation_logged
        # in decide_next_step, so they never re-add here). It's a tenant-
        # config nag, not a safety pause -- the graph already ran to
        # completion, unlike a real escalate_to_human interrupt() --
        # so check_pending_escalation must not treat it as blocking, or a
        # missing closing_link would silently freeze every future message
        # on this conversation.
        escalation_repo = EscalationRepository(runtime.context.session)
        created = await escalation_repo.add(
            Escalation(
                tenant_id=state.tenant_id,
                conversation_id=state.conversation_id,
                reason=state.escalation_reason,
                layer="platform_floor",  # only Layer 1 exists so far (REQUIREMENTS §6)
                status="pending",
                blocks_pipeline=False,
            )
        )
        # book_or_checkout already generated this run's cover reply
        # (state.draft_text) before reaching this node -- no new LLM call
        # needed here, just the internal note explaining why.
        await _write_internal_note(runtime, state, created.id, state.escalation_reason)

    return state


def build_pipeline_graph() -> StateGraph[PipelineState, PipelineContext]:
    graph = StateGraph(PipelineState, context_schema=PipelineContext)

    graph.add_node("load_history", load_history)
    graph.add_node("check_pending_escalation", check_pending_escalation)
    graph.add_node("load_tenant_config", load_tenant_config)
    graph.add_node("understand_intent", understand_intent)
    graph.add_node("search_knowledge", search_knowledge)
    graph.add_node("score_lead", score_lead)
    graph.add_node("decide_next_step", decide_next_step)
    graph.add_node("call_tools", call_tools)
    graph.add_node("keep_chatting", keep_chatting)
    graph.add_node("escalate_to_human", escalate_to_human)
    graph.add_node("book_or_checkout", book_or_checkout)
    graph.add_node("log_lead_and_notify", log_lead_and_notify)

    graph.set_entry_point("load_history")
    graph.add_edge("load_history", "check_pending_escalation")
    graph.add_conditional_edges(
        "check_pending_escalation",
        route_after_escalation_check,
        {"skip": END, "continue": "load_tenant_config"},
    )
    graph.add_edge("load_tenant_config", "understand_intent")
    graph.add_edge("understand_intent", "search_knowledge")
    graph.add_edge("search_knowledge", "score_lead")
    graph.add_edge("score_lead", "decide_next_step")
    graph.add_conditional_edges(
        "decide_next_step",
        route_after_decision,
        {
            "keep_chatting": "call_tools",
            "escalate_to_human": "escalate_to_human",
            "book_or_checkout": "book_or_checkout",
        },
    )
    graph.add_edge("call_tools", "keep_chatting")
    graph.add_edge("keep_chatting", "log_lead_and_notify")
    graph.add_edge("escalate_to_human", "log_lead_and_notify")
    graph.add_edge("book_or_checkout", "log_lead_and_notify")
    graph.add_edge("log_lead_and_notify", END)

    return graph
