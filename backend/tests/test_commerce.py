import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.commerce.connectors import check_inventory, get_order_status
from app.commerce.schemas import InventoryResult, OrderStatusResult
from app.commerce.tools import (
    INVENTORY_CHECK_TOOL,
    ORDER_STATUS_TOOL,
    enabled_tools,
    execute,
    format_result,
)
from app.core.config import settings
from app.tenants.behavior_config import ToolCallingConfig


def _response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code, json=json_body, request=httpx.Request("GET", "http://test")
    )


def _patched_client(get_result: httpx.Response | BaseException) -> MagicMock:
    """Patches httpx.AsyncClient the way app.commerce.connectors uses it --
    `async with httpx.AsyncClient(...) as client: await client.get(...)`."""
    client = AsyncMock()
    if isinstance(get_result, BaseException):
        client.get.side_effect = get_result
    else:
        client.get.return_value = get_result
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=False)
    return context_manager


class TestGetOrderStatus:
    async def test_returns_parsed_result_on_success(self) -> None:
        tenant_id = uuid.uuid4()
        body = {
            "order_number": "12345",
            "status": "shipped",
            "carrier": "UPS",
            "tracking_number": "UP123456789",
            "days_to_delivery": 3,
        }
        with patch(
            "app.commerce.connectors.httpx.AsyncClient",
            return_value=_patched_client(_response(200, body)),
        ):
            result = await get_order_status(tenant_id, "12345")
        assert result == OrderStatusResult.model_validate(body)

    async def test_sends_bearer_token_and_tenant_id(self) -> None:
        tenant_id = uuid.uuid4()
        client_cm = _patched_client(
            _response(200, {"order_number": "1", "status": "processing", "carrier": None,
                             "tracking_number": None, "days_to_delivery": 2})
        )
        with patch("app.commerce.connectors.httpx.AsyncClient", return_value=client_cm):
            await get_order_status(tenant_id, "1")
        client = client_cm.__aenter__.return_value
        _url, kwargs = client.get.call_args
        assert kwargs["params"] == {"tenant_id": str(tenant_id)}
        assert kwargs["headers"] == {
            "Authorization": f"Bearer {settings.fake_commerce_internal_token}"
        }

    async def test_url_encodes_a_garbage_order_number(self) -> None:
        client_cm = _patched_client(
            _response(200, {"order_number": "###???", "status": "not_found", "carrier": None,
                             "tracking_number": None, "days_to_delivery": None})
        )
        with patch("app.commerce.connectors.httpx.AsyncClient", return_value=client_cm):
            await get_order_status(uuid.uuid4(), "###???")
        client = client_cm.__aenter__.return_value
        (url,), _kwargs = client.get.call_args
        assert "###???" not in url
        assert url.endswith("%23%23%23%3F%3F%3F")

    async def test_returns_none_on_connection_error(self) -> None:
        with patch(
            "app.commerce.connectors.httpx.AsyncClient",
            return_value=_patched_client(httpx.ConnectError("boom")),
        ):
            assert await get_order_status(uuid.uuid4(), "12345") is None

    async def test_returns_none_on_non_2xx(self) -> None:
        with patch(
            "app.commerce.connectors.httpx.AsyncClient",
            return_value=_patched_client(_response(500)),
        ):
            assert await get_order_status(uuid.uuid4(), "12345") is None


class TestCheckInventory:
    async def test_returns_parsed_result_on_success(self) -> None:
        tenant_id = uuid.uuid4()
        body = {
            "product_name": "Oversized Hoodie", "size": "M", "carried": True,
            "in_stock": True, "quantity_available": 12, "restock_eta_days": None,
        }
        with patch(
            "app.commerce.connectors.httpx.AsyncClient",
            return_value=_patched_client(_response(200, body)),
        ):
            result = await check_inventory(tenant_id, "Oversized Hoodie", "M")
        assert result == InventoryResult.model_validate(body)

    async def test_not_carried_when_the_platform_says_so(self) -> None:
        body = {
            "product_name": "AK-47", "size": None, "carried": False,
            "in_stock": False, "quantity_available": None, "restock_eta_days": None,
        }
        with patch(
            "app.commerce.connectors.httpx.AsyncClient",
            return_value=_patched_client(_response(200, body)),
        ):
            result = await check_inventory(uuid.uuid4(), "AK-47")
        assert result is not None
        assert result.carried is False

    async def test_omits_size_param_when_not_given(self) -> None:
        tenant_id = uuid.uuid4()
        client_cm = _patched_client(
            _response(200, {
                "product_name": "Widget", "size": None, "carried": True,
                "in_stock": True, "quantity_available": 1, "restock_eta_days": None,
            })
        )
        with patch("app.commerce.connectors.httpx.AsyncClient", return_value=client_cm):
            await check_inventory(tenant_id, "Widget")
        client = client_cm.__aenter__.return_value
        _url, kwargs = client.get.call_args
        assert kwargs["params"] == {"tenant_id": str(tenant_id), "query": "Widget"}

    async def test_returns_none_on_timeout(self) -> None:
        with patch(
            "app.commerce.connectors.httpx.AsyncClient",
            return_value=_patched_client(httpx.TimeoutException("slow")),
        ):
            assert await check_inventory(uuid.uuid4(), "Widget") is None


class TestEnabledTools:
    def test_no_tools_at_defaults(self) -> None:
        assert enabled_tools(ToolCallingConfig()) == []

    def test_order_status_only(self) -> None:
        assert enabled_tools(ToolCallingConfig(order_status_lookup_enabled=True)) == [
            ORDER_STATUS_TOOL
        ]

    def test_both_enabled(self) -> None:
        tools = enabled_tools(
            ToolCallingConfig(order_status_lookup_enabled=True, inventory_check_enabled=True)
        )
        assert tools == [ORDER_STATUS_TOOL, INVENTORY_CHECK_TOOL]


class TestExecute:
    async def test_dispatches_order_status_lookup(self) -> None:
        tenant_id = uuid.uuid4()
        fake_result = OrderStatusResult(
            order_number="12345", status="shipped", carrier="UPS",
            tracking_number="UP1", days_to_delivery=2,
        )
        with patch(
            "app.commerce.tools.get_order_status", AsyncMock(return_value=fake_result)
        ) as mock_fn:
            result = await execute("order_status_lookup", {"order_number": "12345"}, tenant_id)
        mock_fn.assert_awaited_once_with(tenant_id, order_number="12345")
        assert result is fake_result

    async def test_dispatches_inventory_check(self) -> None:
        tenant_id = uuid.uuid4()
        fake_result = InventoryResult(
            product_name="Oversized Hoodie", size="M", carried=True,
            in_stock=True, quantity_available=5, restock_eta_days=None,
        )
        with patch(
            "app.commerce.tools.check_inventory", AsyncMock(return_value=fake_result)
        ) as mock_fn:
            result = await execute(
                "inventory_check", {"product_name": "Oversized Hoodie", "size": "M"}, tenant_id
            )
        mock_fn.assert_awaited_once_with(tenant_id, product_name="Oversized Hoodie", size="M")
        assert result is fake_result

    async def test_connector_returning_none_propagates(self) -> None:
        with patch("app.commerce.tools.get_order_status", AsyncMock(return_value=None)):
            result = await execute(
                "order_status_lookup", {"order_number": "12345"}, uuid.uuid4()
            )
        assert result is None

    async def test_unknown_tool_name_returns_none(self) -> None:
        result = await execute("delete_all_orders", {"order_number": "12345"}, uuid.uuid4())
        assert result is None

    async def test_missing_required_arg_returns_none_not_raises(self) -> None:
        # No mocking needed -- the missing kwarg is a TypeError at the call
        # boundary itself (execute()'s **args unpacking), before the real
        # connector's body -- and therefore any network call -- ever runs.
        result = await execute("order_status_lookup", {}, uuid.uuid4())
        assert result is None

    async def test_unexpected_extra_arg_returns_none_not_raises(self) -> None:
        result = await execute(
            "order_status_lookup", {"order_number": "1", "sabotage": True}, uuid.uuid4()
        )
        assert result is None


class TestFormatResult:
    def test_not_found_order(self) -> None:
        result = OrderStatusResult(
            order_number="###", status="not_found", carrier=None,
            tracking_number=None, days_to_delivery=None,
        )
        assert format_result("order_status_lookup", result) == "No order found matching '###'."

    def test_shipped_order_includes_carrier_and_tracking(self) -> None:
        result = OrderStatusResult(
            order_number="9001",
            status="shipped",
            carrier="UPS",
            tracking_number="UP123456789",
            days_to_delivery=3,
        )
        text = format_result("order_status_lookup", result)
        assert "9001" in text
        assert "shipped" in text
        assert "UPS" in text
        assert "UP123456789" in text
        assert "3 day" in text

    def test_in_stock_inventory(self) -> None:
        result = InventoryResult(
            product_name="Oversized Hoodie", size="M", carried=True, in_stock=True,
            quantity_available=12, restock_eta_days=None,
        )
        text = format_result("inventory_check", result)
        assert "Oversized Hoodie (M)" in text
        assert "in stock" in text
        assert "12" in text

    def test_out_of_stock_inventory(self) -> None:
        result = InventoryResult(
            product_name="Oversized Hoodie", size=None, carried=True, in_stock=False,
            quantity_available=None, restock_eta_days=10,
        )
        text = format_result("inventory_check", result)
        assert "out of stock" in text
        assert "10 day" in text

    def test_not_carried_inventory(self) -> None:
        # The actual regression case (docs/plans/
        # fake-commerce-platform-integration.md): an off-catalog product
        # must read as "we don't carry that", not a fabricated stock answer.
        result = InventoryResult(
            product_name="AK-47", size=None, carried=False, in_stock=False,
            quantity_available=None, restock_eta_days=None,
        )
        text = format_result("inventory_check", result)
        assert "don't carry" in text
        assert "in stock" not in text
        assert "out of stock" not in text
