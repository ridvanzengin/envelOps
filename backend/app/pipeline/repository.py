import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.core.repository import TenantScopedRepository
from app.pipeline.models import PipelineTrace


class PipelineTraceRepository(TenantScopedRepository[PipelineTrace]):
    model = PipelineTrace

    async def record_result(
        self,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        result: dict[str, Any],
    ) -> PipelineTrace:
        """One row per inbound message, capturing just enough of the final
        PipelineState (docs/ARCHITECTURE.md §4) to answer "why did the
        pipeline reply this way" -- not a full per-step trace. Shared by
        the real channel-ingestion path (pipeline/tasks.py) and the Test
        Console (test_console/api.py) so both feed the same diagnostics
        (docs/ROADMAP.md §3.3/§3.4)."""
        return await self.add(
            PipelineTrace(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
                step="result",
                state={
                    "detected_intent": result.get("detected_intent"),
                    "lead_score": result.get("lead_score"),
                    "decision": result.get("decision"),
                },
            )
        )

    async def list_by_conversation(
        self, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[PipelineTrace]:
        stmt = select(PipelineTrace).where(
            PipelineTrace.tenant_id == tenant_id,
            PipelineTrace.conversation_id == conversation_id,
        )
        result = await self.session.scalars(stmt)
        return list(result)

    async def get_latest_by_conversation_ids(
        self, tenant_id: uuid.UUID, conversation_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, PipelineTrace]:
        """One row per conversation -- the most recent trace, keyed by
        conversation_id. Powers the rail/list-row intent+lead-score badges
        (docs/ROADMAP.md §3.3), unlike list_by_conversation's own full
        per-message history."""
        if not conversation_ids:
            return {}
        latest = aliased(PipelineTrace)
        latest_created_at = (
            select(func.max(latest.created_at))
            .where(latest.conversation_id == PipelineTrace.conversation_id)
            .correlate(PipelineTrace)
            .scalar_subquery()
        )
        stmt = select(PipelineTrace).where(
            PipelineTrace.tenant_id == tenant_id,
            PipelineTrace.conversation_id.in_(conversation_ids),
            PipelineTrace.created_at == latest_created_at,
        )
        result = await self.session.scalars(stmt)
        return {trace.conversation_id: trace for trace in result}
