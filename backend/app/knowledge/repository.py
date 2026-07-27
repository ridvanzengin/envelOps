import uuid

from sqlalchemy import delete, func, select

from app.core.repository import TenantScopedRepository
from app.knowledge.models import KnowledgeChunk, KnowledgeSource


class KnowledgeSourceRepository(TenantScopedRepository[KnowledgeSource]):
    model = KnowledgeSource

    async def list_with_chunk_counts(
        self, tenant_id: uuid.UUID
    ) -> list[tuple[KnowledgeSource, int]]:
        """One query, not the list-then-count-per-source N+1 -- there's no
        real reason to prefer that shape once a single grouped query does
        it directly."""
        stmt = (
            select(KnowledgeSource, func.count(KnowledgeChunk.id))
            .outerjoin(
                KnowledgeChunk, KnowledgeChunk.knowledge_source_id == KnowledgeSource.id
            )
            .where(KnowledgeSource.tenant_id == tenant_id)
            .group_by(KnowledgeSource.id)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


class KnowledgeChunkRepository(TenantScopedRepository[KnowledgeChunk]):
    model = KnowledgeChunk

    async def delete_by_source(
        self, tenant_id: uuid.UUID, knowledge_source_id: uuid.UUID
    ) -> None:
        """The "refresh this source" step (REQUIREMENTS §5) -- delete and
        re-embed, no silent staleness. Tenant-scoped in the WHERE clause
        itself, not just relying on the caller having already checked
        ownership of knowledge_source_id."""
        stmt = delete(KnowledgeChunk).where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeChunk.knowledge_source_id == knowledge_source_id,
        )
        await self.session.execute(stmt)

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
