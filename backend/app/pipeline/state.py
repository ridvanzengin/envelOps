import uuid

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
    detected_intent: str | None = None
    retrieved_chunks: list[str] = []
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
