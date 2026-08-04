"""Internal-only fake commerce-platform HTTP API -- called exclusively by
app/commerce/connectors.py, from this same backend, never reachable from
outside it (docs/plans/fake-commerce-platform-integration.md). Shaped
loosely like a real commerce platform's admin API (a product search, an
order-status lookup) -- not full fidelity, same "recognizably
platform-shaped" philosophy app/channels/simulated_client.py already uses
for the simulated channel webhooks."""

import hashlib
import random
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.repository import FakeCommerceProductRepository
from app.commerce.schemas import InventoryResult, OrderStatus, OrderStatusResult
from app.core.config import settings
from app.core.db import get_session

router = APIRouter(prefix="/internal/fake-commerce", tags=["internal"])

_ORDER_STATUSES: list[OrderStatus] = [
    "processing",
    "shipped",
    "out_for_delivery",
    "delivered",
    "cancelled",
]
_CARRIERS = ["USPS", "UPS", "FedEx", "DHL"]


def _seeded_random(*parts: str) -> random.Random:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


async def require_internal_token(authorization: str | None = Header(default=None)) -> None:
    """Fail-closed the same way app/channels/api.py's webhook secret
    header already is -- a missing/still-default token must never mean an
    open endpoint. Not real security either way (nothing outside this
    backend can reach this route), just enough that the connector has to
    build a real Authorization header and handle a real 401, the way it
    would against an actual platform."""
    expected = f"Bearer {settings.fake_commerce_internal_token}"
    if not settings.fake_commerce_internal_token or authorization != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal token")


def _compute_order_status(order_number: str) -> OrderStatusResult:
    """Hash-seeded and deterministic, moved here verbatim from the old
    in-process app/commerce/connectors.py -- not a fabrication-fix target
    itself. Unlike a product name, an arbitrary-looking order number is a
    *normal* thing for a real customer to type; a real platform's API
    would just return "not found" for a made-up one too, so there's no
    bounded fake-orders table to match against here (see the plan doc's
    own reasoning)."""
    cleaned = order_number.strip()
    if not any(c.isalnum() for c in cleaned):
        return OrderStatusResult(
            order_number=order_number,
            status="not_found",
            carrier=None,
            tracking_number=None,
            days_to_delivery=None,
        )

    rng = _seeded_random("order", cleaned.lower())
    order_status = rng.choice(_ORDER_STATUSES)

    if order_status in ("processing", "cancelled"):
        carrier = None
        tracking_number = None
    else:
        carrier = rng.choice(_CARRIERS)
        tracking_number = f"{carrier[:2].upper()}{rng.randint(10**8, 10**9 - 1)}"

    days_to_delivery = (
        rng.randint(1, 7)
        if order_status in ("processing", "shipped", "out_for_delivery")
        else None
    )

    return OrderStatusResult(
        order_number=order_number,
        status=order_status,
        carrier=carrier,
        tracking_number=tracking_number,
        days_to_delivery=days_to_delivery,
    )


@router.get("/orders/{order_number}", response_model=OrderStatusResult)
async def lookup_order_status(
    order_number: str,
    tenant_id: uuid.UUID,
    _: None = Depends(require_internal_token),
) -> OrderStatusResult:
    # tenant_id is accepted (and required) for shape-realism only -- a
    # real platform's order API is always scoped to an account -- but
    # doesn't change the result: there's no per-tenant fake-orders table
    # (deliberately, see the plan doc), just the same hash-seeded logic
    # every tenant shares.
    return _compute_order_status(order_number)


@router.get("/products", response_model=InventoryResult)
async def lookup_inventory(
    tenant_id: uuid.UUID,
    query: str,
    size: str | None = None,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_internal_token),
) -> InventoryResult:
    repo = FakeCommerceProductRepository(session)
    product = await repo.find_matching(tenant_id, query, size)
    if product is None:
        # The actual regression fix (docs/plans/
        # fake-commerce-platform-integration.md): a query with no matching
        # row in this tenant's own catalog comes back genuinely not
        # carried, not a hash-seeded fabrication.
        return InventoryResult(
            product_name=query,
            size=size,
            carried=False,
            in_stock=False,
            quantity_available=None,
            restock_eta_days=None,
        )
    return InventoryResult(
        product_name=query,
        size=size,
        carried=True,
        in_stock=product.in_stock,
        quantity_available=product.quantity_available,
        restock_eta_days=product.restock_eta_days,
    )
