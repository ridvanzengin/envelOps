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


async def _patch_settings(body: dict, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.patch("/tenants/settings", json=body, headers=headers)


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


class TestPatchTenantSettings:
    async def test_rejects_missing_token(self) -> None:
        response = await _patch_settings({"general_context": "hi"}, None)
        assert response.status_code == 401

    async def test_404_when_tenant_not_found(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _patch_settings({"general_context": "hi"}, token)
        assert response.status_code == 404

    async def test_patches_closing_action_and_link_only(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        tenant = _fake_tenant(
            tenant_id,
            behavior_config={"greeting": {"tone": "formal_business"}},
        )
        session = AsyncMock()
        app.dependency_overrides[get_session] = lambda: session
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=tenant)
            response = await _patch_settings(
                {
                    "closing_action": "book_or_checkout",
                    "closing_link": "https://example.com/checkout",
                },
                token,
            )

        assert response.status_code == 200
        assert tenant.closing_action == "book_or_checkout"
        assert tenant.closing_link == "https://example.com/checkout"
        # Behavior config untouched by a closing-only patch.
        body = response.json()
        assert body["behavior_config"]["greeting"]["tone"] == "formal_business"
        session.commit.assert_awaited_once()

    async def test_patches_one_behavior_area_leaving_others_untouched(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        tenant = _fake_tenant(
            tenant_id,
            closing_action="book_or_checkout",
            closing_link="https://example.com/original",
            behavior_config={
                "knowledge_query": {"tone": "formal_business", "not_found_max_distance": 0.5},
            },
        )
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=tenant)
            response = await _patch_settings(
                {"greeting": {"tone": "formal_business", "invite_followup_question": False}},
                token,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["behavior_config"]["greeting"]["tone"] == "formal_business"
        assert body["behavior_config"]["greeting"]["invite_followup_question"] is False
        # Independence: the area that wasn't in this patch is untouched...
        assert body["behavior_config"]["knowledge_query"]["not_found_max_distance"] == 0.5
        # ...and so is closing_action/closing_link, not part of this patch.
        assert body["closing_action"] == "book_or_checkout"
        assert body["closing_link"] == "https://example.com/original"
        assert tenant.behavior_config["knowledge_query"]["not_found_max_distance"] == 0.5

    async def test_patches_channel_overrides_as_one_whole_dict(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        tenant = _fake_tenant(
            tenant_id, behavior_config={"greeting": {"tone": "formal_business"}}
        )
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=tenant)
            response = await _patch_settings(
                {
                    "channel_overrides": {
                        "telegram": {
                            "formality": "formal_email",
                            "include_greeting": True,
                            "include_sign_off": False,
                            "length_guidance": "brief",
                        }
                    }
                },
                token,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["behavior_config"]["channel_overrides"]["telegram"]["formality"] == (
            "formal_email"
        )
        assert body["behavior_config"]["greeting"]["tone"] == "formal_business"

    async def test_patches_general_context_including_clearing_it_to_null(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        tenant = _fake_tenant(
            tenant_id, behavior_config={"general_context": "old context"}
        )
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=tenant)
            response = await _patch_settings({"general_context": None}, token)

        assert response.status_code == 200
        assert response.json()["behavior_config"]["general_context"] is None
        assert tenant.behavior_config["general_context"] is None

    async def test_empty_patch_changes_nothing(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        tenant = _fake_tenant(
            tenant_id,
            closing_action="keep_chatting",
            behavior_config={"greeting": {"tone": "formal_business"}},
        )
        session = AsyncMock()
        app.dependency_overrides[get_session] = lambda: session
        with patch("app.tenants.api.TenantRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=tenant)
            response = await _patch_settings({}, token)

        assert response.status_code == 200
        body = response.json()
        assert body["closing_action"] == "keep_chatting"
        assert body["behavior_config"]["greeting"]["tone"] == "formal_business"
        session.commit.assert_awaited_once()

    async def test_422_on_invalid_closing_action(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        response = await _patch_settings({"closing_action": "not_a_real_action"}, token)
        assert response.status_code == 422

    async def test_422_on_out_of_bounds_not_found_max_distance(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        response = await _patch_settings(
            {"knowledge_query": {"tone": "friendly_business", "not_found_max_distance": 5.0}},
            token,
        )
        assert response.status_code == 422

    async def test_422_on_invalid_literal_in_channel_overrides(self) -> None:
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
        response = await _patch_settings(
            {
                "channel_overrides": {
                    "telegram": {
                        "formality": "not_a_real_formality",
                        "include_greeting": True,
                        "include_sign_off": False,
                        "length_guidance": "brief",
                    }
                }
            },
            token,
        )
        assert response.status_code == 422
