import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.main import app


def _fake_escalation(tenant_id: uuid.UUID) -> MagicMock:
    escalation = MagicMock()
    escalation.id = uuid.uuid4()
    escalation.conversation_id = uuid.uuid4()
    escalation.tenant_id = tenant_id
    escalation.reason = "contraindication language (matched 'allerjik')"
    escalation.layer = "platform_floor"
    escalation.status = "pending"
    escalation.created_at = datetime.now(UTC)
    return escalation


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


async def _list_escalations(token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/escalations", headers=headers)


class TestListEscalations:
    async def test_rejects_missing_token(self) -> None:
        response = await _list_escalations(None)
        assert response.status_code == 401  # HTTPBearer's own "no credentials" code

    async def test_rejects_invalid_token(self) -> None:
        response = await _list_escalations("garbage")
        assert response.status_code == 401

    async def test_returns_only_the_caller_tenants_escalations(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="owner")
        escalation = _fake_escalation(tenant_id)

        with patch("app.escalation.api.EscalationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list = AsyncMock(return_value=[escalation])
            response = await _list_escalations(token)

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(escalation.id)
        assert body[0]["status"] == "pending"
        # list() was called scoped to the token's tenant, not a caller-supplied one
        mock_repo_cls.return_value.list.assert_called_once_with(tenant_id)
