"""Cross-cutting coverage for settings.demo_mode_enabled (app/core/demo_mode.py):
every mutating endpoint it's wired into must 403 with the same message when
it's on, regardless of which module owns the route. Doesn't re-test each
route's own normal (demo_mode off) behavior -- that's each module's own
existing test file's job, and the full suite staying green with demo mode
defaulting to False already proves those are untouched by this change.
"""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.core.demo_mode import DEMO_MODE_MESSAGE, block_in_demo_mode
from app.main import app


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


def _token() -> str:
    return create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")


async def _request(
    method: str, path: str, *, json: dict | None = None, authed: bool = True
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {_token()}"} if authed else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json, headers=headers)


def test_block_in_demo_mode_raises_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.demo_mode.settings.demo_mode_enabled", True)
    with pytest.raises(Exception) as exc_info:
        block_in_demo_mode()
    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    assert exc_info.value.detail == DEMO_MODE_MESSAGE  # type: ignore[attr-defined]


def test_block_in_demo_mode_is_a_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.demo_mode.settings.demo_mode_enabled", False)
    block_in_demo_mode()  # must not raise


# One request per gated route, minimal-but-valid bodies -- the point is
# proving the dependency is actually wired to each real route (a pure
# unit test of block_in_demo_mode() alone wouldn't catch a route missing
# the Depends()), not exercising each route's own business logic.
_GATED_AUTHED_REQUESTS: list[tuple[str, str, dict | None]] = [
    ("POST", "/knowledge/sources", {"type": "manual", "content": "x"}),
    ("POST", "/knowledge/sources/999/refresh", None),
    ("PUT", "/knowledge/sources/999", {"content": "x"}),
    ("DELETE", "/knowledge/sources/999", None),
    ("PATCH", "/tenants/settings", {"closing_action": "escalate_to_human"}),
    (
        "POST",
        f"/escalations/{uuid.uuid4()}/resolve",
        None,
    ),
    ("POST", "/escalations/trigger-phrases", {"phrase": "refund"}),
    ("DELETE", f"/escalations/trigger-phrases/{uuid.uuid4()}", None),
    ("PATCH", f"/channels/{uuid.uuid4()}", {"ai_enabled": False}),
]


class TestDemoModeBlocksAuthedMutations:
    @pytest.mark.parametrize("method,path,body", _GATED_AUTHED_REQUESTS)
    async def test_returns_403_with_demo_message(
        self, monkeypatch: pytest.MonkeyPatch, method: str, path: str, body: dict | None
    ) -> None:
        monkeypatch.setattr("app.core.demo_mode.settings.demo_mode_enabled", True)
        response = await _request(method, path, json=body)
        assert response.status_code == 403
        assert response.json()["detail"] == DEMO_MODE_MESSAGE


_TELEGRAM_UPDATE = {
    "update_id": 1,
    "message": {"chat": {"id": 1}, "text": "hi"},
}
_META_EVENT = {"sender": {"id": "user-1"}, "message": {"text": "hi"}}
_WHATSAPP_MESSAGE = {"from_": "user-1", "text": {"body": "hi"}}
_EMAIL_PAYLOAD = {"from_address": "a@b.test", "text": "hi"}

_GATED_WEBHOOK_REQUESTS: list[tuple[str, dict]] = [
    (f"/channels/telegram/{uuid.uuid4()}/webhook", _TELEGRAM_UPDATE),
    (f"/channels/instagram/{uuid.uuid4()}/webhook", _META_EVENT),
    (f"/channels/facebook/{uuid.uuid4()}/webhook", _META_EVENT),
    (f"/channels/whatsapp/{uuid.uuid4()}/webhook", _WHATSAPP_MESSAGE),
    (f"/channels/email/{uuid.uuid4()}/webhook", _EMAIL_PAYLOAD),
]


class TestDemoModeBlocksInboundWebhooks:
    # Unauthenticated on purpose (real platforms don't send a JWT) -- the
    # demo gate must still fire before any secret-header/channel-lookup
    # logic runs, same as it does for authed routes above.
    @pytest.mark.parametrize("path,body", _GATED_WEBHOOK_REQUESTS)
    async def test_returns_403_with_demo_message(
        self, monkeypatch: pytest.MonkeyPatch, path: str, body: dict
    ) -> None:
        monkeypatch.setattr("app.core.demo_mode.settings.demo_mode_enabled", True)
        response = await _request("POST", path, json=body, authed=False)
        assert response.status_code == 403
        assert response.json()["detail"] == DEMO_MODE_MESSAGE
