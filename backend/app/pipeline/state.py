import uuid
from typing import Any

from pydantic import BaseModel


class PipelineState(BaseModel):
    """Carried through the 8-step LangGraph run; see docs/ARCHITECTURE.md §4.
    Checkpointed at the safety-gate pause point."""

    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    incoming_text: str
    # No default -- forces every caller to consciously supply it, same as
    # tenant_id/conversation_id. Drives keep_chatting/book_or_checkout's
    # channel-specific reply tone (app/pipeline/graph.py); an unrecognized
    # value falls back to the chat-style default there rather than erroring.
    channel_type: str
    # Populated by load_history, the graph's own first node (docs/ROADMAP.md
    # §2) -- callers never set this themselves, unlike every other field
    # above. Prior messages in this conversation, oldest first, each
    # pre-formatted as "Customer: ..."/"You: ...", capped to the most
    # recent load_history._HISTORY_MAX_MESSAGES. Empty for a conversation's
    # first message, same as before this field existed.
    conversation_history: list[str] = []
    # Populated once by load_tenant_config (right after
    # check_pending_escalation) -- Tenant.behavior_config's raw dict, not
    # the parsed app.tenants.behavior_config.TenantBehaviorConfig. Stays a
    # plain dict deliberately: this state is checkpointed by LangGraph's
    # Postgres checkpointer across the escalate_to_human pause, and a
    # plain dict is a proven-safe shape for that (PipelineTrace.state
    # already is one) -- a nested Pydantic model's behavior under
    # LangGraph's own state serializer, across a schema change made
    # between a pause and its resume, is untested risk not worth taking.
    # Every node that needs the typed view calls
    # load_tenant_behavior_config(state.tenant_behavior_config) locally --
    # cheap, pure, no I/O, safe to call more than once per run.
    tenant_behavior_config: dict[str, Any] = {}
    # Set by check_pending_escalation, the graph's second node
    # (docs/ROADMAP.md §3.1) -- True routes straight to END with no LLM
    # calls at all, since a blocking pending Escalation already exists for
    # this conversation and nothing new should be decided until a human
    # resolves it.
    already_escalated: bool = False
    detected_intent: str | None = None
    retrieved_chunks: list[str] = []
    # Populated by call_tools (right before keep_chatting) when the tenant
    # has opted into a fake connector (app/commerce/) and the model decides
    # a tool call is actually needed -- one formatted fact string per
    # successful call, same shape/spirit as retrieved_chunks (plain list of
    # primitives, checkpointer-safe) and folded into keep_chatting's same
    # context block. Empty for every tenant that hasn't opted in, which is
    # every tenant today.
    tool_call_results: list[str] = []
    lead_score: str | None = None
    decision: str | None = None
    draft_text: str | None = None
    escalation_reason: str | None = None
    # Set by decide_next_step's safety-floor branch, right after it logs the
    # Escalation row itself (docs/ARCHITECTURE.md §5) -- lets
    # log_lead_and_notify know not to log the same escalation again once
    # this run resumes past the pause. book_or_checkout's own,
    # unrelated escalate-on-missing-closing_link case never touches this
    # flag, so it still gets logged there, exactly once, as before.
    escalation_logged: bool = False
