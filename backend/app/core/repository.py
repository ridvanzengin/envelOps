import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import TenantScopedMixin

# Bound to TenantScopedMixin, not Base: every concrete model here is both
# (Base for the ORM mapping, TenantScopedMixin for id/tenant_id), but only
# the mixin actually declares those two columns, so that's what mypy needs
# to know about to type-check self.model.tenant_id / self.model.id below.
ModelT = TypeVar("ModelT", bound=TenantScopedMixin)


class TenantScopedRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: uuid.UUID, id: uuid.UUID) -> ModelT | None:
        stmt = select(self.model).where(
            self.model.tenant_id == tenant_id, self.model.id == id
        )
        return await self.session.scalar(stmt)

    async def list(self, tenant_id: uuid.UUID) -> list[ModelT]:
        stmt = select(self.model).where(self.model.tenant_id == tenant_id)
        result = await self.session.scalars(stmt)
        return list(result)

    async def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        return obj
