import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import decode_access_token, hash_password
from app.core.db import get_session
from app.main import app


def _fake_user(**overrides: object) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.tenant_id = uuid.uuid4()
    user.role = "owner"
    user.email = "owner@honeyco.test"
    user.hashed_password = hash_password("correct-password")
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


async def _login(email: str, password: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/auth/login", json={"email": email, "password": password})


async def _get_dev_tenants() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/auth/dev-tenants")


async def _dev_login(user_id: uuid.UUID) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/auth/dev-login", json={"user_id": str(user_id)})


class TestLogin:
    async def test_correct_credentials_return_token_for_that_user(self) -> None:
        user = _fake_user()
        with patch("app.auth.api.UserRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email_unscoped = AsyncMock(return_value=user)
            response = await _login(user.email, "correct-password")

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        payload = decode_access_token(body["access_token"])
        assert payload["sub"] == str(user.id)
        assert payload["tenant_id"] == str(user.tenant_id)
        assert payload["role"] == "owner"

    async def test_wrong_password_rejected(self) -> None:
        user = _fake_user()
        with patch("app.auth.api.UserRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email_unscoped = AsyncMock(return_value=user)
            response = await _login(user.email, "wrong-password")
        assert response.status_code == 401

    async def test_unknown_email_rejected_with_same_generic_message(self) -> None:
        with patch("app.auth.api.UserRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_email_unscoped = AsyncMock(return_value=None)
            unknown_response = await _login("nobody@nowhere.test", "whatever")
        with patch("app.auth.api.UserRepository") as mock_repo_cls:
            user = _fake_user()
            mock_repo_cls.return_value.get_by_email_unscoped = AsyncMock(return_value=user)
            wrong_password_response = await _login(user.email, "wrong-password")

        assert unknown_response.status_code == wrong_password_response.status_code == 401
        assert unknown_response.json()["detail"] == wrong_password_response.json()["detail"]


class TestDevAuthBypassDisabled:
    # The default, and the only acceptable state outside a local machine
    # (settings.dev_auth_bypass_enabled's own docstring) -- both endpoints
    # must 404, not just refuse, so a real deployment doesn't reveal this
    # exists at all.
    async def test_dev_tenants_404s_when_disabled(self) -> None:
        with patch("app.auth.api.settings.dev_auth_bypass_enabled", False):
            response = await _get_dev_tenants()
        assert response.status_code == 404

    async def test_dev_login_404s_when_disabled(self) -> None:
        with patch("app.auth.api.settings.dev_auth_bypass_enabled", False):
            response = await _dev_login(uuid.uuid4())
        assert response.status_code == 404


class TestDevAuthBypassEnabled:
    async def test_lists_tenants_with_their_owner(self) -> None:
        tenant = type("Tenant", (), {"id": uuid.uuid4(), "name": "Honey Co"})()
        user = _fake_user(tenant_id=tenant.id)
        with (
            patch("app.auth.api.settings.dev_auth_bypass_enabled", True),
            patch("app.auth.api.TenantRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.list_with_owner_unscoped = AsyncMock(
                return_value=[(tenant, user)]
            )
            response = await _get_dev_tenants()
        assert response.status_code == 200
        assert response.json() == [
            {
                "user_id": str(user.id),
                "tenant_id": str(tenant.id),
                "tenant_name": "Honey Co",
                "email": user.email,
            }
        ]

    async def test_logs_in_as_the_chosen_user_with_no_password_check(self) -> None:
        user = _fake_user()
        with (
            patch("app.auth.api.settings.dev_auth_bypass_enabled", True),
            patch("app.auth.api.UserRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=user)
            response = await _dev_login(user.id)
        assert response.status_code == 200
        payload = decode_access_token(response.json()["access_token"])
        assert payload["sub"] == str(user.id)
        assert payload["tenant_id"] == str(user.tenant_id)
        assert payload["role"] == "owner"

    async def test_404s_for_an_unknown_user_id(self) -> None:
        with (
            patch("app.auth.api.settings.dev_auth_bypass_enabled", True),
            patch("app.auth.api.UserRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=None)
            response = await _dev_login(uuid.uuid4())
        assert response.status_code == 404


class TestDevAuthBypassOpenedByDemoMode:
    # demo_mode_enabled ORs into the same gate (app/auth/api.py's
    # _require_dev_bypass_enabled) even with dev_auth_bypass_enabled left
    # False -- a public demo needs the no-password tenant switch (now the
    # Dashboard's own tenant dropdown) without also being a general local-
    # dev auth bypass.
    async def test_dev_tenants_reachable_with_only_demo_mode_enabled(self) -> None:
        tenant = type("Tenant", (), {"id": uuid.uuid4(), "name": "Honey Co"})()
        user = _fake_user(tenant_id=tenant.id)
        with (
            patch("app.auth.api.settings.dev_auth_bypass_enabled", False),
            patch("app.auth.api.settings.demo_mode_enabled", True),
            patch("app.auth.api.TenantRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.list_with_owner_unscoped = AsyncMock(
                return_value=[(tenant, user)]
            )
            response = await _get_dev_tenants()
        assert response.status_code == 200

    async def test_dev_login_reachable_with_only_demo_mode_enabled(self) -> None:
        user = _fake_user()
        with (
            patch("app.auth.api.settings.dev_auth_bypass_enabled", False),
            patch("app.auth.api.settings.demo_mode_enabled", True),
            patch("app.auth.api.UserRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=user)
            response = await _dev_login(user.id)
        assert response.status_code == 200
