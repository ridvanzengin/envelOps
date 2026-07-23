"""The fixed 8-step pipeline (docs/ARCHITECTURE.md §4). Node bodies are not
implemented yet — this file wires up the sequence/branching so the shape is
settled before the logic (LLM calls, vector search, notifications) lands.

Step 1 ("incoming message") happens before this graph runs — the channel
ingestion path (§7) normalizes the message and hands off to Celery, which
builds the initial PipelineState and invokes the graph starting at step 2.
Step 8 (follow-up) is a separate Celery-triggered re-entry at step 2, not a
node in this graph.
"""

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

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

# First-pass taxonomy, not a validated product design (REQUIREMENTS.md §2
# says per-business config is deferred) — deliberately generic across all
# four business models in §2's table rather than honey-seller-specific,
# since nothing in the data model yet lets this vary per tenant. Revisit
# once real synthetic/pilot messages (§12) show what's actually missing.
_INTENT_LABELS = frozenset(
    {"knowledge_question", "purchase_intent", "complaint_or_problem", "small_talk", "other"}
)

# Also a first-pass default, not tenant-configurable yet (ARCHITECTURE §4:
# "plain LLM call for now"; REQUIREMENTS §2: "what counts as a hot lead"
# must eventually be per-business config). "cold" is the fallback on an
# unrecognized model response, not "warm" — understating a lead's readiness
# is the safer default than overstating it.
_LEAD_SCORES = frozenset({"hot", "warm", "cold"})


def understand_intent(state: PipelineState) -> PipelineState:
    prompt = (
        "Classify the intent of this customer DM into exactly one of: "
        f"{', '.join(sorted(_INTENT_LABELS))}. "
        "The message may be in Turkish or English — respond in neither, "
        "just the single label, nothing else, no punctuation.\n\n"
        f"Message: {state.incoming_text}"
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
        "general question, no buying signal. The message may be in "
        "Turkish or English. Reply with only the single label, nothing "
        "else, no punctuation.\n\n"
        f"Message: {state.incoming_text}\n"
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
        return state

    state.decision = "keep_chatting"
    return state


def route_after_decision(state: PipelineState) -> str:
    """Reads state.decision (set by decide_next_step) to pick a branch."""
    if state.decision is None:
        raise ValueError("decide_next_step must set state.decision before routing")
    return state.decision


def keep_chatting(state: PipelineState) -> PipelineState:
    context_block = (
        "\n".join(f"- {chunk}" for chunk in state.retrieved_chunks)
        if state.retrieved_chunks
        else "(no matching knowledge found for this question)"
    )
    prompt = (
        "You are a helpful customer support assistant for a small business, "
        "replying directly to a customer's DM. Keep it short and natural, "
        "like a real person texting back — no \"Dear customer\" greeting, "
        "no signature. Only use the knowledge below if it's actually "
        "relevant to the question; if it doesn't answer the question, say "
        "so honestly rather than guessing.\n\n"
        f"Relevant knowledge:\n{context_block}\n\n"
        "Customer message (your reply MUST be in this exact same language "
        f"— do not translate, do not switch languages): {state.incoming_text}"
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


def book_or_checkout(state: PipelineState) -> PipelineState:
    raise NotImplementedError


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

    if state.decision == "escalate_to_human" and state.escalation_reason is not None:
        escalation_repo = EscalationRepository(runtime.context.session)
        await escalation_repo.add(
            Escalation(
                tenant_id=state.tenant_id,
                conversation_id=state.conversation_id,
                reason=state.escalation_reason,
                layer="platform_floor",  # only Layer 1 exists so far (REQUIREMENTS §6)
                status="pending",
            )
        )

    return state


def build_pipeline_graph() -> StateGraph[PipelineState, PipelineContext]:
    graph = StateGraph(PipelineState, context_schema=PipelineContext)

    graph.add_node("understand_intent", understand_intent)
    graph.add_node("search_knowledge", search_knowledge)
    graph.add_node("score_lead", score_lead)
    graph.add_node("decide_next_step", decide_next_step)
    graph.add_node("keep_chatting", keep_chatting)
    graph.add_node("escalate_to_human", escalate_to_human)
    graph.add_node("book_or_checkout", book_or_checkout)
    graph.add_node("log_lead_and_notify", log_lead_and_notify)

    graph.set_entry_point("understand_intent")
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
