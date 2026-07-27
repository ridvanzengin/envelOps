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
