import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin

EMBEDDING_DIM = 1536  # must match whatever hosted embedding API is configured


class KnowledgeSource(Base, TenantScopedMixin):
    __tablename__ = "knowledge_sources"

    type: Mapped[str] = mapped_column(nullable=False)  # url | pdf | manual
    source_uri: Mapped[str | None] = mapped_column(nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeChunk(Base, TenantScopedMixin):
    __tablename__ = "knowledge_chunks"

    knowledge_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
