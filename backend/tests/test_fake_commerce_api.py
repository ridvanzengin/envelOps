import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import httpx
import pytest

from app.core.config import settings
from app.core.db import get_session
from app.main import app


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token is not None else {}


async def _get(path: str, params: dict[str, str], token: str | None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, params=params, headers=_headers(token))


def _order_url(order_number: str) -> str:
    return f"/internal/fake-commerce/orders/{quote(order_number, safe='')}"


class TestInternalAuth:
    """Same auth check on both routes (require_internal_token) -- tested
    thoroughly once here via the orders route, same "identical for both,
    covered once" approach app/channels/api.py's own webhook auth tests
    already take for their 4 simulated platforms."""

    async def test_rejects_missing_token(self) -> None:
        response = await _get(_order_url("12345"), {"tenant_id": str(uuid.uuid4())}, None)
        assert response.status_code == 401

    async def test_rejects_wrong_token(self) -> None:
        response = await _get(_order_url("12345"), {"tenant_id": str(uuid.uuid4())}, "wrong")
        assert response.status_code == 401

    async def test_accepts_the_configured_token(self) -> None:
        response = await _get(
            _order_url("12345"),
            {"tenant_id": str(uuid.uuid4())},
            settings.fake_commerce_internal_token,
        )
        assert response.status_code == 200


class TestOrderStatusLookup:
    async def test_deterministic_for_the_same_order_number(self) -> None:
        params = {"tenant_id": str(uuid.uuid4())}
        token = settings.fake_commerce_internal_token
        first = await _get(_order_url("12345"), params, token)
        second = await _get(_order_url("12345"), params, token)
        assert first.json() == second.json()

    async def test_garbage_order_number_is_not_found(self) -> None:
        response = await _get(
            _order_url("###???"),
            {"tenant_id": str(uuid.uuid4())},
            settings.fake_commerce_internal_token,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "not_found"

    async def test_result_shape_matches_the_declared_status_set(self) -> None:
        response = await _get(
            _order_url("order-42"),
            {"tenant_id": str(uuid.uuid4())},
            settings.fake_commerce_internal_token,
        )
        assert response.json()["status"] in (
            "processing", "shipped", "out_for_delivery", "delivered", "cancelled", "not_found",
        )


class TestInventoryLookup:
    async def test_returns_carried_true_on_a_catalog_match(self) -> None:
        product = MagicMock(in_stock=True, quantity_available=12, restock_eta_days=None)
        with patch(
            "app.commerce.fake_platform_api.FakeCommerceProductRepository"
        ) as mock_repo_cls:
            mock_repo_cls.return_value.find_matching = AsyncMock(return_value=product)
            response = await _get(
                "/internal/fake-commerce/products",
                {"tenant_id": str(uuid.uuid4()), "query": "Oversized Hoodie", "size": "M"},
                settings.fake_commerce_internal_token,
            )
        assert response.status_code == 200
        body = response.json()
        assert body["carried"] is True
        assert body["in_stock"] is True
        assert body["quantity_available"] == 12

    async def test_returns_carried_false_on_no_match(self) -> None:
        # The actual regression test for the live-found AK-47 case
        # (docs/plans/fake-commerce-platform-integration.md): a genuinely
        # off-catalog query comes back not-carried, not a fabrication.
        with patch(
            "app.commerce.fake_platform_api.FakeCommerceProductRepository"
        ) as mock_repo_cls:
            mock_repo_cls.return_value.find_matching = AsyncMock(return_value=None)
            response = await _get(
                "/internal/fake-commerce/products",
                {"tenant_id": str(uuid.uuid4()), "query": "AK-47"},
                settings.fake_commerce_internal_token,
            )
        assert response.status_code == 200
        body = response.json()
        assert body["carried"] is False
        assert body["in_stock"] is False
        assert body["quantity_available"] is None

    async def test_passes_tenant_id_and_size_to_the_repository(self) -> None:
        tenant_id = uuid.uuid4()
        with patch(
            "app.commerce.fake_platform_api.FakeCommerceProductRepository"
        ) as mock_repo_cls:
            mock_repo_cls.return_value.find_matching = AsyncMock(return_value=None)
            await _get(
                "/internal/fake-commerce/products",
                {"tenant_id": str(tenant_id), "query": "Widget", "size": "L"},
                settings.fake_commerce_internal_token,
            )
        mock_repo_cls.return_value.find_matching.assert_awaited_once_with(
            tenant_id, "Widget", "L"
        )
