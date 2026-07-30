import uuid
from collections import defaultdict

from sqlalchemy import Select, delete, select

from app.core.repository import TenantScopedRepository
from app.knowledge.models import KnowledgeChunk, KnowledgeSource


def _build_search_stmt(
    tenant_id: uuid.UUID,
    query_embedding: list[float],
    *,
    limit: int,
    max_distance: float | None,
) -> Select[tuple[KnowledgeChunk]]:
    """Split out from search_similar for testability -- lets a plain
    offline test compile this statement and inspect its SQL without a
    real database, since this repo has no existing precedent for a
    real-DB repository test to follow instead."""
    distance = KnowledgeChunk.embedding.cosine_distance(query_embedding)
    stmt = select(KnowledgeChunk).where(KnowledgeChunk.tenant_id == tenant_id)
    if max_distance is not None:
        stmt = stmt.where(distance <= max_distance)
    return stmt.order_by(distance).limit(limit)


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
        self,
        tenant_id: uuid.UUID,
        query_embedding: list[float],
        *,
        limit: int = 5,
        max_distance: float | None = None,
    ) -> list[KnowledgeChunk]:
        """Tenant-scoped pgvector cosine-similarity search (ARCHITECTURE
        §6) — never crosses tenant boundaries, same as every other query
        here (ARCHITECTURE §2).

        max_distance is a cosine_distance ceiling (0=identical ..
        ~2=opposite). None (default) reproduces this method's original
        behavior exactly -- no filtering, always the top-K nearest
        chunks regardless of true relevance. Filtered in the query
        itself (the WHERE uses the same distance expression the ORDER
        BY does), not post-filtered in Python -- `limit` still means
        "up to N *matching* chunks," not "N chunks, some discarded
        after." Root-cause fix for a real bug (docs/ROADMAP.md §3.6):
        with no floor, an entirely unrelated question always retrieved
        *some* chunks, and the model treated "some knowledge exists" as
        "just needs narrowing down" instead of "wrong topic entirely."
        """
        stmt = _build_search_stmt(
            tenant_id, query_embedding, limit=limit, max_distance=max_distance
        )
        result = await self.session.scalars(stmt)
        return list(result)
