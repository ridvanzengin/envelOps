import uuid

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
