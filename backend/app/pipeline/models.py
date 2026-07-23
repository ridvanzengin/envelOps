import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin

# LangGraph's own checkpoint table (pause/resume state for the safety-gate
# escalation, see docs/ARCHITECTURE.md §5) is managed by its Postgres
# checkpointer, not defined here.


class PipelineTrace(Base, TenantScopedMixin):
    __tablename__ = "pipeline_traces"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False
    )
    step: Mapped[str] = mapped_column(nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
