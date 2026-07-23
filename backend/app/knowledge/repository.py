from app.core.repository import TenantScopedRepository
from app.knowledge.models import KnowledgeChunk, KnowledgeSource


class KnowledgeSourceRepository(TenantScopedRepository[KnowledgeSource]):
    model = KnowledgeSource


class KnowledgeChunkRepository(TenantScopedRepository[KnowledgeChunk]):
    model = KnowledgeChunk
