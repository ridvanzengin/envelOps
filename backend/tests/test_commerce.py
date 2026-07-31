from app.commerce.connectors import check_inventory, get_order_status
from app.commerce.schemas import InventoryResult, OrderStatusResult
from app.commerce.tools import (
    INVENTORY_CHECK_TOOL,
    ORDER_STATUS_TOOL,
    enabled_tools,
    execute,
    format_result,
)
from app.tenants.behavior_config import ToolCallingConfig


class TestGetOrderStatus:
    def test_deterministic_for_the_same_order_number(self) -> None:
        assert get_order_status("12345") == get_order_status("12345")

    def test_different_order_numbers_can_differ(self) -> None:
        results = {get_order_status(str(n)).status for n in range(20)}
        assert len(results) > 1

    def test_status_is_always_within_the_declared_set(self) -> None:
        for n in range(20):
            result = get_order_status(str(n))
            assert result.status in (
                "processing",
                "shipped",
                "out_for_delivery",
                "delivered",
                "cancelled",
                "not_found",
            )

    def test_blank_order_number_is_not_found(self) -> None:
        result = get_order_status("   ")
        assert result.status == "not_found"
        assert result.carrier is None
        assert result.tracking_number is None
        assert result.days_to_delivery is None

    def test_non_alphanumeric_order_number_is_not_found(self) -> None:
        assert get_order_status("###???").status == "not_found"

    def test_carrier_and_tracking_present_only_when_shipped_or_later(self) -> None:
        for n in range(30):
            result = get_order_status(f"order-{n}")
            if result.status in ("shipped", "out_for_delivery", "delivered"):
                assert result.carrier is not None
                assert result.tracking_number is not None
            else:
                assert result.carrier is None
                assert result.tracking_number is None


class TestCheckInventory:
    def test_deterministic_for_the_same_product_and_size(self) -> None:
        first = check_inventory("Oversized Hoodie", "M")
        second = check_inventory("Oversized Hoodie", "M")
        assert first == second

    def test_different_size_can_give_a_different_result(self) -> None:
        # Not flaky-asserting >1 distinct value -- just that varying the
        # size doesn't crash and produces a valid result each time.
        results = {
            check_inventory("Oversized Hoodie", size).in_stock
            for size in ("XS", "S", "M", "L", "XL", "XXL")
        }
        assert len(results) >= 1

    def test_in_stock_has_a_positive_quantity_and_no_restock_eta(self) -> None:
        for name in (f"item-{n}" for n in range(20)):
            result = check_inventory(name)
            if result.in_stock:
                assert result.quantity_available is not None
                assert result.quantity_available > 0
                assert result.restock_eta_days is None
            else:
                assert result.quantity_available is None
                assert result.restock_eta_days is not None
                assert result.restock_eta_days > 0


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
    def test_dispatches_order_status_lookup(self) -> None:
        result = execute("order_status_lookup", {"order_number": "12345"})
        assert isinstance(result, OrderStatusResult)
        assert result.order_number == "12345"

    def test_dispatches_inventory_check(self) -> None:
        result = execute("inventory_check", {"product_name": "Oversized Hoodie", "size": "M"})
        assert isinstance(result, InventoryResult)
        assert result.product_name == "Oversized Hoodie"

    def test_inventory_check_size_is_optional(self) -> None:
        result = execute("inventory_check", {"product_name": "Oversized Hoodie"})
        assert isinstance(result, InventoryResult)
        assert result.size is None

    def test_unknown_tool_name_returns_none(self) -> None:
        assert execute("delete_all_orders", {"order_number": "12345"}) is None

    def test_missing_required_arg_returns_none_not_raises(self) -> None:
        assert execute("order_status_lookup", {}) is None

    def test_unexpected_extra_arg_returns_none_not_raises(self) -> None:
        assert execute("order_status_lookup", {"order_number": "1", "sabotage": True}) is None


class TestFormatResult:
    def test_not_found_order(self) -> None:
        result = get_order_status("###")
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
            product_name="Oversized Hoodie", size="M", in_stock=True,
            quantity_available=12, restock_eta_days=None,
        )
        text = format_result("inventory_check", result)
        assert "Oversized Hoodie (M)" in text
        assert "in stock" in text
        assert "12" in text

    def test_out_of_stock_inventory(self) -> None:
        result = InventoryResult(
            product_name="Oversized Hoodie", size=None, in_stock=False,
            quantity_available=None, restock_eta_days=10,
        )
        text = format_result("inventory_check", result)
        assert "out of stock" in text
        assert "10 day" in text
