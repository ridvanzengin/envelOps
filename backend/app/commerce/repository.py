import uuid

from sqlalchemy import Select, func, select

from app.commerce.models import FakeCommerceProduct
from app.core.repository import TenantScopedRepository


def _build_match_stmt(
    tenant_id: uuid.UUID, name: str, size: str | None
) -> Select[tuple[FakeCommerceProduct]]:
    """Split out from find_matching for testability -- lets a plain
    offline test compile this statement and inspect its SQL without a real
    database, same approach app/knowledge/repository.py's
    _build_search_stmt already takes (this repo has no existing precedent
    for a real-DB repository test).

    Exact, case-insensitive match on name (and size, when given) -- not a
    fuzzy/substring match. Deliberate: the whole point of a bounded catalog
    is that an off-catalog query (an out-of-domain product, or someone
    trying "ak47 rifle") comes back genuinely not carried, not "close
    enough" to something real. If size is omitted, any size row for the
    name matches (ordered for determinism, not aggregated across variants
    -- see the plan doc's "lean flat" note)."""
    stmt = select(FakeCommerceProduct).where(
        FakeCommerceProduct.tenant_id == tenant_id,
        func.lower(FakeCommerceProduct.name) == name.strip().lower(),
    )
    if size is not None:
        stmt = stmt.where(func.lower(FakeCommerceProduct.size) == size.strip().lower())
    return stmt.order_by(FakeCommerceProduct.size)


class FakeCommerceProductRepository(TenantScopedRepository[FakeCommerceProduct]):
    model = FakeCommerceProduct

    async def find_matching(
        self, tenant_id: uuid.UUID, name: str, size: str | None
    ) -> FakeCommerceProduct | None:
        return await self.session.scalar(_build_match_stmt(tenant_id, name, size))
