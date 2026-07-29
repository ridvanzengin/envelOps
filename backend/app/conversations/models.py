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
    # docs/ROADMAP.md §3.1 -- customer: sent to the customer over their
    # channel and visible to them; internal: an escalation note, visible
    # only to the business owner in this app, never sent anywhere.
    # Default keeps every historical row (and every ordinary reply) as
    # "customer" with no backfill needed.
    audience: Mapped[str] = mapped_column(nullable=False, default="customer")
    # Set only for audience="internal" rows -- which specific Escalation
    # this note explains, so the frontend can show a Resolve action on it
    # while that escalation is still pending and drop it once resolved.
    escalation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("escalations.id"), nullable=True
    )
