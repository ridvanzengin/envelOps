import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin


class Escalation(Base, TenantScopedMixin):
    __tablename__ = "escalations"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(nullable=False)
    layer: Mapped[str] = mapped_column(nullable=False)  # platform_floor | business_rule
    status: Mapped[str] = mapped_column(nullable=False, default="pending")


class TenantTriggerPhrase(Base, TenantScopedMixin):
    """Tenant additions to the Layer 1 safety floor (docs/REQUIREMENTS.md
    §6) — additive only. No columns for category/regex/enabled-toggle: a
    tenant adds a plain phrase, nothing else, and there is deliberately no
    way to edit or disable a system default through this table."""

    __tablename__ = "escalation_trigger_phrases"

    phrase: Mapped[str] = mapped_column(nullable=False)
