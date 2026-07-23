import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin


class Lead(Base, TenantScopedMixin):
    __tablename__ = "leads"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True
    )
    score: Mapped[str] = mapped_column(nullable=False)  # hot | warm | cold
    notes: Mapped[str | None] = mapped_column(nullable=True)
