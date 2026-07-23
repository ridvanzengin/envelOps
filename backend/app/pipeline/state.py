import uuid

from pydantic import BaseModel


class PipelineState(BaseModel):
    """Carried through the 8-step LangGraph run; see docs/ARCHITECTURE.md §4.
    Checkpointed at the safety-gate pause point."""

    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    incoming_text: str
    detected_intent: str | None = None
    retrieved_chunks: list[str] = []
    lead_score: str | None = None
    decision: str | None = None
    draft_text: str | None = None
    escalation_reason: str | None = None
