import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.models import Tenant


class TenantRepository:
    """Not tenant-scoped like other repositories — Tenant is the scope root."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: uuid.UUID) -> Tenant | None:
        return await self.session.scalar(select(Tenant).where(Tenant.id == id))

    async def add(self, tenant: Tenant) -> Tenant:
        self.session.add(tenant)
        await self.session.flush()
        return tenant
