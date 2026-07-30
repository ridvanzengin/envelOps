import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.main import app


def _fake_tenant(tenant_id: uuid.UUID, **overrides: object) -> MagicMock:
    tenant = MagicMock()
    tenant.id = tenant_id
    tenant.closing_action = "escalate_to_human"
    tenant.closing_link = None
    tenant.behavior_config = {}
    for key, value in overrides.items():
        setattr(tenant, key, value)
    return tenant


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


async def _get_settings(token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/tenants/settings", headers=headers)


async def _put_settings(body: dict, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.put("/tenants/settings", json=body, headers=headers)


_VALID_BODY = {
    "closing_action": "book_or_checkout",
    "closing_link": "https://example.com/checkout",
    "behavior_config": {
        "schema_version": 1,
        "greeting": {"tone": "formal_business", "invite_followup_question": False},
        "off_topic": {"tone": "friendly_business"},
        "knowledge_query": {"tone": "friendly_business", "not_found_max_distance": 0.5},
        "complaint": {"empathetic_acknowledgment": True},
        "lead_handling": {
            "closing_action_override": None,
            "hot_lead_requires_purchase_intent": False,
        },
        "escalation_cover": {"tone": "friendly_business"},
        "book_or_checkout": {"cta_style": "direct_cta"},
        "channel_overrides": {},
        "general_context": None,
    },
}


class TestGetTenantSettings:
    async def test_rejects_missing_token(self) -> None:
        response = await _get_settings(None)
        assert response.status_code == 401

    async def test_rejects_invalid_token(self) -> None:
        response = await _get_settings("garbage")
        assert response.status_code == 401

    async def test_404_when_tenant_not_found(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _get_settings(token)
        assert response.status_code == 404

    async def test_returns_defaults_filled_behavior_config_for_empty_stored_dict(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        tenant = _fake_tenant(tenant_id, behavior_config={})
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=tenant)
            response = await _get_settings(token)

        assert response.status_code == 200
        body = response.json()
        assert body["closing_action"] == "escalate_to_human"
        assert body["closing_link"] is None
        assert body["behavior_config"]["schema_version"] == 1
        assert body["behavior_config"]["greeting"]["tone"] == "friendly_business"
        mock_repo_cls.return_value.get.assert_called_once_with(tenant_id)

    async def test_returns_defaults_filled_behavior_config_for_partial_dict(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        tenant = _fake_tenant(
            tenant_id, behavior_config={"greeting": {"tone": "formal_business"}}
        )
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=tenant)
            response = await _get_settings(token)

        assert response.status_code == 200
        body = response.json()
        assert body["behavior_config"]["greeting"]["tone"] == "formal_business"
        # Untouched areas still default-filled, not missing.
        assert body["behavior_config"]["off_topic"]["tone"] == "friendly_business"


class TestUpdateTenantSettings:
    async def test_rejects_missing_token(self) -> None:
        response = await _put_settings(_VALID_BODY, None)
        assert response.status_code == 401

    async def test_404_when_tenant_not_found(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _put_settings(_VALID_BODY, token)
        assert response.status_code == 404

    async def test_persists_closing_fields_and_behavior_config(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        tenant = _fake_tenant(tenant_id)
        session = AsyncMock()
        app.dependency_overrides[get_session] = lambda: session
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=tenant)
            response = await _put_settings(_VALID_BODY, token)

        assert response.status_code == 200
        body = response.json()
        assert body["closing_action"] == "book_or_checkout"
        assert body["closing_link"] == "https://example.com/checkout"
        lead_handling = body["behavior_config"]["lead_handling"]
        assert lead_handling["hot_lead_requires_purchase_intent"] is False
        assert tenant.closing_action == "book_or_checkout"
        assert tenant.closing_link == "https://example.com/checkout"
        assert tenant.behavior_config["knowledge_query"]["not_found_max_distance"] == 0.5
        session.commit.assert_awaited_once()

    async def test_422_on_invalid_closing_action(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        body = {**_VALID_BODY, "closing_action": "not_a_real_action"}
        response = await _put_settings(body, token)
        assert response.status_code == 422

    async def test_422_on_out_of_bounds_not_found_max_distance(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        body = {
            **_VALID_BODY,
            "behavior_config": {
                **_VALID_BODY["behavior_config"],
                "knowledge_query": {
                    "tone": "friendly_business",
                    "not_found_max_distance": 5.0,
                },
            },
        }
        response = await _put_settings(body, token)
        assert response.status_code == 422

    async def test_422_on_invalid_literal_in_channel_overrides(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        body = {
            **_VALID_BODY,
            "behavior_config": {
                **_VALID_BODY["behavior_config"],
                "channel_overrides": {
                    "telegram": {
                        "formality": "not_a_real_formality",
                        "include_greeting": True,
                        "include_sign_off": False,
                        "length_guidance": "brief",
                    }
                },
            },
        }
        response = await _put_settings(body, token)
        assert response.status_code == 422
