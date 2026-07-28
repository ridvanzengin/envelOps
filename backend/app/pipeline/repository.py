import uuid

from sqlalchemy import select

from app.core.repository import TenantScopedRepository
from app.pipeline.models import PipelineTrace


class PipelineTraceRepository(TenantScopedRepository[PipelineTrace]):
    model = PipelineTrace

    async def list_by_conversation(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[PipelineTrace]:
        stmt = select(PipelineTrace).where(
            PipelineTrace.tenant_id == tenant_id,
            PipelineTrace.conversation_id == conversation_id,
        )
        result = await self.session.scalars(stmt)
        return list(result)
