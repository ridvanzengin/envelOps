"""The only file that knows about both app.core.llm's tool-calling types
and the fake connectors -- builds the per-tenant-enabled tool list,
dispatches a model's tool call by name, and formats the fake result into
the plain fact strings app/pipeline/graph.py's call_tools node puts on
PipelineState.tool_call_results (same shape/spirit as retrieved_chunks)."""

import uuid
from typing import Any

from pydantic import BaseModel

from app.commerce.connectors import check_inventory, get_order_status
from app.commerce.schemas import InventoryResult, OrderStatusResult
from app.core.llm import ToolDeclaration
from app.tenants.behavior_config import ToolCallingConfig

ORDER_STATUS_TOOL = ToolDeclaration(
    name="order_status_lookup",
    description=(
        "Look up the current status of a customer's order by order number. "
        "Only call this when the customer's own order number is clearly "
        "given or already known from the conversation -- never guess one."
    ),
    parameters={
        "type": "object",
        "properties": {
            "order_number": {
                "type": "string",
                "description": "The customer's order number, exactly as given.",
            }
        },
        "required": ["order_number"],
    },
)

INVENTORY_CHECK_TOOL = ToolDeclaration(
    name="inventory_check",
    description=(
        "Check whether a specific product (and size/variant, if relevant) "
        "is currently in stock."
    ),
    parameters={
        "type": "object",
        "properties": {
            "product_name": {
                "type": "string",
                "description": "The product being asked about.",
            },
            "size": {
                "type": "string",
                "description": "Size or variant, if the customer mentioned one.",
            },
        },
        "required": ["product_name"],
    },
)


def enabled_tools(config: ToolCallingConfig) -> list[ToolDeclaration]:
    tools = []
    if config.order_status_lookup_enabled:
        tools.append(ORDER_STATUS_TOOL)
    if config.inventory_check_enabled:
        tools.append(INVENTORY_CHECK_TOOL)
    return tools


async def execute(name: str, args: dict[str, Any], tenant_id: uuid.UUID) -> BaseModel | None:
    """Never raises -- a hallucinated tool name or a malformed/missing arg
    from the model degrades to "no result" (call_tools just skips it),
    the same posture understand_intent takes on an unrecognized label. The
    connectors extend this same guarantee through their real HTTP call
    (app/commerce/connectors.py) -- a timeout or failed request also comes
    back as None here, not a raised exception. tenant_id comes from
    PipelineState, never the model's own args -- it scopes the fake
    platform's catalog lookup, not something to trust the model to supply."""
    try:
        if name == ORDER_STATUS_TOOL.name:
            return await get_order_status(tenant_id, **args)
        if name == INVENTORY_CHECK_TOOL.name:
            return await check_inventory(tenant_id, **args)
    except TypeError:
        return None
    return None


def format_result(name: str, result: BaseModel) -> str:
    if isinstance(result, OrderStatusResult):
        if result.status == "not_found":
            return f"No order found matching '{result.order_number}'."
        parts = [f"Order {result.order_number} status: {result.status.replace('_', ' ')}."]
        if result.carrier and result.tracking_number:
            parts.append(
                f"Carrier: {result.carrier}, tracking number: {result.tracking_number}."
            )
        if result.days_to_delivery is not None:
            parts.append(f"Estimated {result.days_to_delivery} day(s) until delivery.")
        return " ".join(parts)

    if isinstance(result, InventoryResult):
        label = result.product_name + (f" ({result.size})" if result.size else "")
        if not result.carried:
            return f"We don't carry {label} -- no matching product in our catalog."
        if result.in_stock:
            return f"{label} is in stock, {result.quantity_available} available."
        return (
            f"{label} is currently out of stock, expected back in about "
            f"{result.restock_eta_days} day(s)."
        )

    return str(result)  # unreachable given execute()'s own dispatch, kept defensive
