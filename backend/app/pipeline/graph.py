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

import uuid
from datetime import UTC, datetime

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.conversations.models import Message
from app.conversations.repository import MessageRepository
from app.core.llm import embed_text, generate_text
from app.escalation.models import Escalation
from app.escalation.repository import EscalationRepository, TenantTriggerPhraseRepository
from app.escalation.safety_gate import check_safety_floor
from app.knowledge.repository import KnowledgeChunkRepository
from app.leads.models import Lead
from app.leads.repository import LeadRepository
from app.pipeline.context import PipelineContext
from app.pipeline.state import PipelineState
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

# Also a first-pass default, not tenant-configurable yet (ARCHITECTURE §4:
# "plain LLM call for now"; REQUIREMENTS §2: "what counts as a hot lead"
# must eventually be per-business config). "cold" is the fallback on an
# unrecognized model response, not "warm" — understating a lead's readiness
# is the safer default than overstating it.
_LEAD_SCORES = frozenset({"hot", "warm", "cold"})

# First-pass, generic, not tenant-configurable yet -- same "revisit once
# real usage shows what's missing" status as _INTENT_LABELS/_LEAD_SCORES
# above. Drives keep_chatting/book_or_checkout's reply tone; validated via
# the Test Console (frontend TestConsole.tsx), not synthetic messages,
# since tone is a presentational property the synthetic harness's own
# "does this look right to a human" standard doesn't really cover on its
# own -- send the same question through multiple channels and compare.
_CHANNEL_TONE_GUIDANCE: dict[str, str] = {
    "email": (
        "This reply is an EMAIL. Use a brief greeting, complete sentences, "
        "a slightly more formal/professional register than a chat message, "
        "and a short sign-off. It's fine for this to run a few sentences "
        "if the question needs it."
    ),
    "telegram": (
        "This reply is a TELEGRAM message. Keep it short and casual, like "
        "a real person texting back -- no greeting, no sign-off."
    ),
    "whatsapp": (
        "This reply is a WHATSAPP message. Keep it short and casual, like "
        "a real person texting back -- no greeting, no sign-off."
    ),
    "instagram": (
        "This reply is an INSTAGRAM DM. Keep it short and casual, like a "
        "real person texting back -- no greeting, no sign-off."
    ),
    "facebook": (
        "This reply is a FACEBOOK MESSENGER DM. Keep it short and casual, "
        "like a real person texting back -- no greeting, no sign-off."
    ),
}
# Chat-style, not email-style -- matches every real channel built so far
# (Telegram) and every disabled-rail channel besides email, so an
# unrecognized channel_type reads the same way those already do rather
# than silently turning formal.
_DEFAULT_CHANNEL_TONE = _CHANNEL_TONE_GUIDANCE["telegram"]


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
    tone_guidance = _CHANNEL_TONE_GUIDANCE.get(state.channel_type, _DEFAULT_CHANNEL_TONE)
    return generate_text(
        "You are a helpful customer support assistant for a small "
        f"business, replying directly to a customer's message. "
        f"{tone_guidance} This specific question needs a colleague to "
        "weigh in before you can answer it properly -- let them know "
        "briefly and naturally (not robotic, not apologetic-sounding) "
        "that you'll confirm and get back to them shortly. Do not guess "
        "an answer, and do not mention any specific policy, safety, or "
        "eligibility reason.\n\n"
        f"{_history_block(state)}"
        "Customer's latest message (your reply MUST be in this exact "
        f"same language -- do not translate): {state.incoming_text}"
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
    # REQUIREMENTS §12 stage 1 synthetic testing:
    # a hypothetical pre-purchase question ("what if I don't like it, can I
    # return it?") classified as knowledge_question in Turkish but
    # complaint_or_problem in English, because nothing told the model where
    # that boundary actually sits. The hypothetical-vs-actual distinction
    # below is what's supposed to make the same underlying question land on
    # the same label regardless of which language it's asked in.
    prompt = (
        "Classify the intent of this customer DM into exactly one of: "
        f"{', '.join(sorted(_INTENT_LABELS))}.\n\n"
        "Label definitions -- apply these the same way regardless of "
        "which language the message is in; the same underlying question "
        "must get the same label whether asked in Turkish or English:\n"
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
        "Respond in neither Turkish nor English — just the single label, "
        "nothing else, no punctuation.\n\n"
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
    query_embedding = embed_text(state.incoming_text, task_type="RETRIEVAL_QUERY")
    chunk_repo = KnowledgeChunkRepository(runtime.context.session)
    chunks = await chunk_repo.search_similar(
        state.tenant_id, query_embedding, limit=_KNOWLEDGE_SEARCH_TOP_K
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
        "than that message would suggest in isolation. The message may be "
        "in Turkish or English. Reply with only the single label, nothing "
        "else, no punctuation.\n\n"
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
    if state.lead_score == "hot" and state.detected_intent == "purchase_intent":
        tenant_repo = TenantRepository(runtime.context.session)
        tenant = await tenant_repo.get(state.tenant_id)
        # A missing tenant row shouldn't be possible in practice (state.tenant_id
        # comes from an already-authenticated context), but if it somehow
        # happened, defaulting to auto-send here would be exactly backwards.
        state.decision = tenant.closing_action if tenant is not None else "escalate_to_human"
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


def keep_chatting(state: PipelineState) -> PipelineState:
    tone_guidance = _CHANNEL_TONE_GUIDANCE.get(state.channel_type, _DEFAULT_CHANNEL_TONE)

    # Found via real Test Console usage (not synthetic testing -- REQUIREMENTS
    # §12's fixed message list never included a bare greeting/check-in): the
    # strict grounding instruction below used to apply unconditionally, so a
    # plain "merhaba"/"you there?" -- small_talk, not a real question --
    # still got the "I don't have that information" disclaimer, since there
    # was nothing in the knowledge base about greetings either. Only
    # information-seeking intents actually need the "don't guess" rule; a
    # greeting just needs a greeting back.
    if state.detected_intent in _INTENTS_NEEDING_GROUNDING:
        context_block = (
            "\n".join(f"- {chunk}" for chunk in state.retrieved_chunks)
            if state.retrieved_chunks
            else "(no matching knowledge found for this question)"
        )
        # The stronger, more explicit anti-hallucination wording below
        # (naming prices/policies/guarantees specifically, and calling out
        # Turkish by name) exists because of a real synthetic-test finding
        # (REQUIREMENTS §12 stage 1): a Turkish
        # price question got told "prices are fixed" -- not present
        # anywhere in the knowledge base in either language -- while the
        # English equivalent correctly declined to guess. The original
        # single soft "say so honestly" line wasn't forceful enough for
        # the model to hold the line equally well in both languages.
        #
        # The clarifying-question branch (docs/ROADMAP.md §3.2) is checked
        # FIRST, before the disclaimer -- an ambiguous question ("kırmızı
        # var mı?" with no product named) isn't "missing from the
        # knowledge base," it's missing a detail needed to even look it up,
        # and the honest disclaimer was the wrong response to that case,
        # not just an unhelpful one. Relies on conversation_history (§2) to
        # ask at most one: if the model already asked a clarifying question
        # last turn, it shows up in the history block below, so the
        # customer's reply lands in branch 2/3 instead of asking again.
        content_instruction = (
            "Ground your reply ONLY in the knowledge listed below. Decide "
            "which of these three situations applies, in this order:\n"
            "1. The message is missing a detail you'd need before you could "
            "even look this up -- e.g. asking about the price/availability/"
            "color of \"it\" or \"the red one\" without saying which product, "
            "and the earlier conversation doesn't already say which one. "
            "In this case, ask exactly ONE short, natural clarifying "
            "question to find out what they mean -- do not guess, do not "
            "answer partially, and do not say a person will confirm "
            "anything, since this is just one follow-up question, not an "
            "escalation.\n"
            "2. Otherwise, the knowledge below explicitly contains the "
            "answer -- answer using only that information.\n"
            "3. Otherwise (the question is specific enough, but the "
            "answer — including specific facts like prices, policies, or "
            "guarantees — simply isn't in the knowledge below), you MUST "
            "say you don't have that information and a person will "
            "confirm, rather than guessing or inferring an answer that "
            "merely sounds plausible.\n"
            "Apply this the same way in every language; do not be any less "
            "careful in Turkish than you would be in English.\n\n"
            f"Relevant knowledge:\n{context_block}\n\n"
        )
    else:
        content_instruction = (
            "This message isn't asking a specific question (it's a greeting, "
            "small talk, or similar) -- there's nothing to ground in a "
            "knowledge base here, so just reply naturally and "
            "conversationally instead (e.g. a greeting gets a greeting "
            "back). Do not say you don't have information or that someone "
            "will follow up; nothing was actually asked.\n\n"
        )

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
        "Customer's latest message (your reply MUST be in this exact same "
        f"language — do not translate, do not switch languages): {state.incoming_text}"
    )
    state.draft_text = generate_text(prompt)
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
        tone_guidance = _CHANNEL_TONE_GUIDANCE.get(state.channel_type, _DEFAULT_CHANNEL_TONE)
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
            "Customer's latest message (your reply MUST be in this exact "
            f"same language — do not translate): {state.incoming_text}"
        )
        return state

    tone_guidance = _CHANNEL_TONE_GUIDANCE.get(state.channel_type, _DEFAULT_CHANNEL_TONE)
    prompt = (
        "You are a helpful customer support assistant for a small business, "
        f"replying directly to a customer's message. {tone_guidance} The "
        "customer is ready to buy/book right now — reply naturally and "
        "include this exact link so they can complete it themselves: "
        f"{closing_link}\n\n"
        f"{_history_block(state)}"
        "Customer's latest message (your reply MUST be in this exact same "
        f"language — do not translate, do not switch languages): {state.incoming_text}"
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
    graph.add_node("understand_intent", understand_intent)
    graph.add_node("search_knowledge", search_knowledge)
    graph.add_node("score_lead", score_lead)
    graph.add_node("decide_next_step", decide_next_step)
    graph.add_node("keep_chatting", keep_chatting)
    graph.add_node("escalate_to_human", escalate_to_human)
    graph.add_node("book_or_checkout", book_or_checkout)
    graph.add_node("log_lead_and_notify", log_lead_and_notify)

    graph.set_entry_point("load_history")
    graph.add_edge("load_history", "check_pending_escalation")
    graph.add_conditional_edges(
        "check_pending_escalation",
        route_after_escalation_check,
        {"skip": END, "continue": "understand_intent"},
    )
    graph.add_edge("understand_intent", "search_knowledge")
    graph.add_edge("search_knowledge", "score_lead")
    graph.add_edge("score_lead", "decide_next_step")
    graph.add_conditional_edges(
        "decide_next_step",
        route_after_decision,
        {
            "keep_chatting": "keep_chatting",
            "escalate_to_human": "escalate_to_human",
            "book_or_checkout": "book_or_checkout",
        },
    )
    graph.add_edge("keep_chatting", "log_lead_and_notify")
    graph.add_edge("escalate_to_human", "log_lead_and_notify")
    graph.add_edge("book_or_checkout", "log_lead_and_notify")
    graph.add_edge("log_lead_and_notify", END)

    return graph
