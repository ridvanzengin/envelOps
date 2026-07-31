import uuid
from datetime import datetime

from sqlalchemy import select

from app.core.repository import TenantScopedRepository
from app.leads.models import Lead


class LeadRepository(TenantScopedRepository[Lead]):
    model = Lead

    async def list_in_range(
        self, tenant_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[Lead]:
        """Dashboard aggregates (app/dashboard/service.py) -- leads created
        in [start, end), for the hot-leads stat tile."""
        stmt = select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.created_at >= start,
            Lead.created_at < end,
        )
        result = await self.session.scalars(stmt)
        return list(result)
