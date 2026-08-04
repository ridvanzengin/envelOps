import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
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

    async def list_with_owner_unscoped(self) -> list[tuple[Tenant, User]]:
        """Demo mode's tenant switcher (docs/ROADMAP.md, app/auth/api.py's
        GET /auth/demo-tenants) -- every tenant alongside one of its users,
        for the Dashboard's own dropdown. Cross-tenant by design, same
        reasoning as every other *_unscoped method (CLAUDE.md's
        tenant-scoping section); gated by settings.demo_mode_enabled at
        the API layer, not here. An inner join, not outer -- a tenant with
        no user yet (e.g.
        scripts/run_synthetic_conversations.py's tenant, which creates no
        User row) can't be logged into anyway, so it's correctly absent
        from this list. Phase 1's single-owner-role model (ARCHITECTURE
        §2) means one row per tenant in practice, not a real multi-user
        fan-out to worry about yet.
        """
        stmt = select(Tenant, User).join(User, User.tenant_id == Tenant.id)
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
