from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import TenantScopedMixin


class FakeCommerceProduct(Base, TenantScopedMixin):
    """The bounded per-tenant catalog app/commerce/fake_platform_api.py's
    product-lookup endpoint matches against -- the actual fix for
    check_inventory's old "any string produces a plausible in-stock
    answer" fabrication (docs/plans/fake-commerce-platform-integration.md):
    a product not present in a tenant's rows here is, correctly, not
    carried, rather than hash-seeded into an invented answer."""

    __tablename__ = "fake_commerce_products"

    name: Mapped[str] = mapped_column(nullable=False)
    # Flat optional string, not a separate variant table -- matches
    # check_inventory's existing signature exactly, and nothing today
    # demands more (see the plan doc's own "lean flat" reasoning).
    size: Mapped[str | None] = mapped_column(nullable=True)
    in_stock: Mapped[bool] = mapped_column(nullable=False)
    quantity_available: Mapped[int | None] = mapped_column(nullable=True)
    restock_eta_days: Mapped[int | None] = mapped_column(nullable=True)
