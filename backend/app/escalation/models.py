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
    # True for the two real interrupt()-based safety-gate pauses
    # (decide_next_step's safety-floor and hot-purchase-intent-default
    # branches); False for log_lead_and_notify's book_or_checkout-fallback
    # catch (a tenant-config nag -- missing closing_link -- that never
    # actually pauses the graph). `layer` can't disambiguate these two
    # cases itself (both are "platform_floor"), so this is what
    # check_pending_escalation (app/pipeline/graph.py, docs/ROADMAP.md
    # §3.1) filters on to avoid treating a config issue as a full
    # conversation freeze.
    blocks_pipeline: Mapped[bool] = mapped_column(nullable=False, default=True)


class TenantTriggerPhrase(Base, TenantScopedMixin):
    """Tenant additions to the Layer 1 safety floor (docs/REQUIREMENTS.md
    §6). No columns for category/regex/enabled-toggle: a tenant adds a
    plain phrase, nothing else, and there is deliberately no way to edit
    or disable a *system default* through this table -- that part stays
    immutable. The tenant's own rows here, unlike defaults, can be
    deleted (`DELETE /escalations/trigger-phrases/{id}`, added
    2026-07-29 -- a deliberate reversal of this table's original
    additive-only design; REQUIREMENTS §6 has the full trade-off)."""

    __tablename__ = "escalation_trigger_phrases"

    phrase: Mapped[str] = mapped_column(nullable=False)
