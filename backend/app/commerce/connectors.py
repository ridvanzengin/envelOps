"""Fake commerce connectors -- deliberately stateless, DB-free, and
network-free. This project simulates commerce-platform integrations
(order tracking, inventory) on purpose: a real Shopify/WooCommerce/etc.
connector needs real credentials and an external account, which is out of
scope for what this project demonstrates (AI behavior orchestration and
safe tool-calling, not third-party API integration work). The real part
is the tool-calling mechanism itself (app/core/llm.py's
generate_with_tools) -- only the data these functions return is fake.

Hash-seeded and deterministic, not random per call: the same order_number
(or product_name+size pair) always returns the same result. This is
deliberate, not incidental -- it makes a calibration review reproducible
(the same test DM always gets the same fake order data back) and lets
tests assert exact values instead of "looks plausible."
"""

import hashlib
import random

from app.commerce.schemas import InventoryResult, OrderStatus, OrderStatusResult

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


def get_order_status(order_number: str) -> OrderStatusResult:
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
    status = rng.choice(_ORDER_STATUSES)

    if status in ("processing", "cancelled"):
        carrier = None
        tracking_number = None
    else:
        carrier = rng.choice(_CARRIERS)
        tracking_number = f"{carrier[:2].upper()}{rng.randint(10**8, 10**9 - 1)}"

    days_to_delivery = (
        rng.randint(1, 7) if status in ("processing", "shipped", "out_for_delivery") else None
    )

    return OrderStatusResult(
        order_number=order_number,
        status=status,
        carrier=carrier,
        tracking_number=tracking_number,
        days_to_delivery=days_to_delivery,
    )


def check_inventory(product_name: str, size: str | None = None) -> InventoryResult:
    rng = _seeded_random(
        "inventory", product_name.strip().lower(), (size or "").strip().lower()
    )
    in_stock = rng.random() < 0.7

    return InventoryResult(
        product_name=product_name,
        size=size,
        in_stock=in_stock,
        quantity_available=rng.randint(1, 50) if in_stock else None,
        restock_eta_days=None if in_stock else rng.randint(3, 21),
    )
