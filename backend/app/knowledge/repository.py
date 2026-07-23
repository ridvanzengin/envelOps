import uuid

from sqlalchemy import select

from app.core.repository import TenantScopedRepository
from app.knowledge.models import KnowledgeChunk, KnowledgeSource


class KnowledgeSourceRepository(TenantScopedRepository[KnowledgeSource]):
    model = KnowledgeSource


class KnowledgeChunkRepository(TenantScopedRepository[KnowledgeChunk]):
    model = KnowledgeChunk

    async def search_similar(
        self, tenant_id: uuid.UUID, query_embedding: list[float], *, limit: int = 5
    ) -> list[KnowledgeChunk]:
        """Tenant-scoped pgvector cosine-similarity search (ARCHITECTURE
        §6) — never crosses tenant boundaries, same as every other query
        here (ARCHITECTURE §2)."""
        stmt = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.tenant_id == tenant_id)
            .order_by(KnowledgeChunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result)
