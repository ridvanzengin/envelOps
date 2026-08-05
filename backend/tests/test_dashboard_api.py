import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.dashboard.service import DashboardSummary
from app.main import app


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


def _token(tenant_id: uuid.UUID | None = None) -> str:
    return create_access_token(
        user_id=uuid.uuid4(), tenant_id=tenant_id or uuid.uuid4(), role="owner"
    )


def _fake_summary(**overrides: object) -> DashboardSummary:
    defaults: dict[str, object] = {
        "range_days": 30,
        "total_conversations": 0,
        "total_conversations_prev": 0,
        "hot_leads": 0,
        "hot_leads_prev": 0,
        "complaints": 0,
        "complaints_prev": 0,
        "escalated": 0,
        "escalated_prev": 0,
        "avg_response_minutes": None,
        "conversations_trend": [],
        "hot_leads_trend": [],
        "complaints_trend": [],
        "escalated_trend": [],
        "intent_breakdown": [],
        "channels": [],
    }
    defaults.update(overrides)
    return DashboardSummary(**defaults)  # type: ignore[arg-type]


async def _get_summary(token: str | None, days: int | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    params = {"days": days} if days is not None else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/dashboard/summary", headers=headers, params=params)


class TestGetSummary:
    async def test_rejects_missing_token(self) -> None:
        response = await _get_summary(None)
        assert response.status_code == 401

    async def test_returns_the_computed_summary_for_the_callers_tenant(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        with patch(
            "app.dashboard.api.compute_summary", new_callable=AsyncMock
        ) as mock_compute:
            mock_compute.return_value = _fake_summary(total_conversations=7)
            response = await _get_summary(token)

        assert response.status_code == 200
        assert response.json()["total_conversations"] == 7
        args, _ = mock_compute.call_args
        assert args[1] == tenant_id
        assert args[2] == 7

    async def test_defaults_to_7_days_and_accepts_1_and_30(self) -> None:
        token = _token()
        with patch(
            "app.dashboard.api.compute_summary", new_callable=AsyncMock
        ) as mock_compute:
            mock_compute.return_value = _fake_summary()
            await _get_summary(token)
            assert mock_compute.call_args.args[2] == 7

            await _get_summary(token, days=1)
            assert mock_compute.call_args.args[2] == 1

            await _get_summary(token, days=30)
            assert mock_compute.call_args.args[2] == 30

    async def test_rejects_an_unsupported_days_value(self) -> None:
        token = _token()
        response = await _get_summary(token, days=14)
        assert response.status_code == 422
