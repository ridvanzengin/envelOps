import uuid
from collections import defaultdict

from sqlalchemy import delete, select

from app.core.repository import TenantScopedRepository
from app.knowledge.models import KnowledgeChunk, KnowledgeSource


class KnowledgeSourceRepository(TenantScopedRepository[KnowledgeSource]):
    model = KnowledgeSource

    async def list_with_chunks(
        self, tenant_id: uuid.UUID
    ) -> list[tuple[KnowledgeSource, list[KnowledgeChunk]]]:
        """One query for sources, one query for every one of their chunks --
        two queries total regardless of source count, not a
        list-then-fetch-chunks-per-source N+1. Chunks ordered by
        created_at, the order _ingest_chunks (app/knowledge/api.py)
        originally inserted them in -- good enough to reconstruct a
        manual source's original text for viewing/editing, not a strict
        guarantee for ties within the same millisecond.
        """
        sources = await self.list(tenant_id)
        if not sources:
            return []
        source_ids = [source.id for source in sources]
        chunks_stmt = (
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeChunk.knowledge_source_id.in_(source_ids),
            )
            .order_by(KnowledgeChunk.created_at.asc())
        )
        chunks = list(await self.session.scalars(chunks_stmt))
        chunks_by_source: dict[uuid.UUID, list[KnowledgeChunk]] = defaultdict(list)
        for chunk in chunks:
            chunks_by_source[chunk.knowledge_source_id].append(chunk)
        return [(source, chunks_by_source.get(source.id, [])) for source in sources]


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
