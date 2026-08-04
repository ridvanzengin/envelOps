"""Result shapes for the fake connectors (app/commerce/connectors.py) --
plain Pydantic models, never persisted anywhere. This is showcase data:
the project deliberately simulates commerce-platform integrations
(Shopify/WooCommerce/etc.) rather than building real ones -- see
app/commerce/connectors.py's own docstring for why."""

from typing import Literal

from pydantic import BaseModel

OrderStatus = Literal[
    "processing", "shipped", "out_for_delivery", "delivered", "cancelled", "not_found"
]


class OrderStatusResult(BaseModel):
    order_number: str
    status: OrderStatus
    carrier: str | None
    tracking_number: str | None
    # None once the order is delivered/cancelled/not_found -- there's
    # nothing left to count down to.
    days_to_delivery: int | None


class InventoryResult(BaseModel):
    product_name: str
    size: str | None
    # False when the tenant's own catalog (app/commerce/models.py's
    # FakeCommerceProduct) has no matching row at all -- the actual fix
    # for the old fabrication bug (docs/plans/
    # fake-commerce-platform-integration.md): an off-catalog query now
    # genuinely comes back "we don't carry that" instead of a plausible
    # in-stock/restock-ETA answer. in_stock/quantity_available/
    # restock_eta_days are all meaningless (False/None/None) when this is
    # False.
    carried: bool
    in_stock: bool
    quantity_available: int | None  # None when not in_stock
    restock_eta_days: int | None  # None when in_stock
