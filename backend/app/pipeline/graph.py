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

from app.core.llm import generate_text
from app.escalation.repository import TenantTriggerPhraseRepository
from app.escalation.safety_gate import check_safety_floor
from app.pipeline.context import PipelineContext
from app.pipeline.state import PipelineState

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


def search_knowledge(state: PipelineState) -> PipelineState:
    raise NotImplementedError


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

    # Past the safety floor, "what counts as hot" and "what closing looks
    # like" are per-tenant configuration (REQUIREMENTS.md §2), which doesn't
    # exist in the data model yet — not implemented until that config does.
    raise NotImplementedError


def route_after_decision(state: PipelineState) -> str:
    """Reads state.decision (set by decide_next_step) to pick a branch."""
    if state.decision is None:
        raise ValueError("decide_next_step must set state.decision before routing")
    return state.decision


def keep_chatting(state: PipelineState) -> PipelineState:
    raise NotImplementedError


def escalate_to_human(state: PipelineState) -> PipelineState:
    """The safety-gate pause point (§5, §6) — the only pause in Phase 1.
    Compiling this graph with a checkpointer (Postgres-backed) and calling
    `interrupt()` here is what makes the pause/resume durable; that wiring
    lives wherever the graph is compiled and invoked, not in this module."""
    raise NotImplementedError


def book_or_checkout(state: PipelineState) -> PipelineState:
    raise NotImplementedError


def log_lead_and_notify(state: PipelineState) -> PipelineState:
    raise NotImplementedError


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
