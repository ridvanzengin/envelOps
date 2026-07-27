import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin


class Conversation(Base, TenantScopedMixin):
    __tablename__ = "conversations"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id"), nullable=False
    )
    external_contact_id: Mapped[str] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(nullable=False, default="open")
    # Set once follow_up_check (docs/ARCHITECTURE.md §4 step 8) sends its
    # one nudge for a quiet conversation -- caps it at exactly one
    # follow-up ever, not resent on every periodic scan. Null means "never
    # followed up" (or the conversation isn't quiet), not "not applicable".
    followed_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Message(Base, TenantScopedMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(nullable=False)  # inbound | outbound
    text: Mapped[str] = mapped_column(nullable=False)
