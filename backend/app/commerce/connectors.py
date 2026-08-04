"""Fake commerce connectors -- each makes a real HTTP call to
app/commerce/fake_platform_api.py, a "commerce platform" endpoint mounted
by this same backend and never reachable from outside it. This project
simulates commerce-platform integrations (order tracking, inventory) on
purpose: a real Shopify/WooCommerce/etc. connector needs real credentials
and an external account, out of scope for what this project demonstrates
(AI behavior orchestration and safe tool-calling, not third-party API
integration work). The real parts are the tool-calling mechanism itself
(app/core/llm.py's generate_with_tools) and, as of this module, the actual
HTTP round-trip and its failure handling -- only the platform on the other
end of the call is fake. See docs/plans/fake-commerce-platform-integration.md
for the full design.

app/commerce/tools.py's execute() guarantees it never raises -- a
hallucinated tool name or a malformed arg degrades to "no result" there.
These functions extend that same guarantee through to real I/O: a
timeout, connection failure, or unexpected non-2xx from the fake endpoint
returns None here too, exactly the kind of failure handling a real
integration would need, worth writing for real rather than assuming the
fake endpoint never fails.
"""

import logging
import uuid
from urllib.parse import quote

import httpx

from app.commerce.schemas import InventoryResult, OrderStatusResult
from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.fake_commerce_internal_token}"}


async def get_order_status(
    tenant_id: uuid.UUID, order_number: str
) -> OrderStatusResult | None:
    # order_number is customer-supplied and deliberately unvalidated
    # (a garbage string is a legitimate "not found" case, computed
    # server-side) -- URL-quoted so it's always a single, unambiguous
    # path segment regardless of what characters it contains.
    url = (
        f"{settings.internal_api_base_url}/internal/fake-commerce/orders/"
        f"{quote(order_number, safe='')}"
    )
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(
                url, params={"tenant_id": str(tenant_id)}, headers=_auth_headers()
            )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Fake commerce platform order lookup failed", exc_info=True)
        return None
    return OrderStatusResult.model_validate(response.json())


async def check_inventory(
    tenant_id: uuid.UUID, product_name: str, size: str | None = None
) -> InventoryResult | None:
    url = f"{settings.internal_api_base_url}/internal/fake-commerce/products"
    params: dict[str, str] = {"tenant_id": str(tenant_id), "query": product_name}
    if size is not None:
        params["size"] = size
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params=params, headers=_auth_headers())
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Fake commerce platform inventory lookup failed", exc_info=True)
        return None
    return InventoryResult.model_validate(response.json())
