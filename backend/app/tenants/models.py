import uuid
from typing import Any

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(nullable=False)

    # What a hot, purchase-intent lead gets routed to past the safety floor
    # (REQUIREMENTS §2: "what closing looks like" must be per-business, not
    # hardcoded per vertical) -- one of the pipeline's own branch names
    # (keep_chatting | escalate_to_human | book_or_checkout), not a separate
    # "business model" concept translated into one, since that indirection
    # has no other use yet. Defaults to escalate_to_human: a business gets
    # autonomous closing by explicitly opting in, not by default.
    closing_action: Mapped[str] = mapped_column(nullable=False, default="escalate_to_human")

    # The link book_or_checkout sends a hot, ready-to-buy/book customer --
    # a Stripe Payment Link, a Calendly URL, a WhatsApp catalog link,
    # whatever the business already uses. Deliberately just a URL, not a
    # platform-specific connector (REQUIREMENTS §5's "manually-updated
    # fallback" framing, applied to closing rather than pricing/inventory):
    # works for any business regardless of what platform they're on, and a
    # real Shopify/Calendly API integration later is an addition alongside
    # this, not a replacement of it -- some tenants will never connect a
    # platform and still need this to work.
    closing_link: Mapped[str | None] = mapped_column(nullable=True)

    # Raw storage for app.tenants.behavior_config.TenantBehaviorConfig --
    # a dumb dict at the DB layer (same pattern as PipelineTrace.state,
    # app/pipeline/models.py, this repo's only other loosely-typed JSON
    # column), validated only at the app boundary via
    # load_tenant_behavior_config(). Plain JSON, not postgresql.JSONB --
    # always read whole by tenant_id PK lookup, never filtered on its
    # internal contents, so JSONB's indexing/containment-query
    # advantages buy nothing here.
    behavior_config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
