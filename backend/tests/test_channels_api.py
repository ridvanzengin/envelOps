import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.main import app


def _fake_channel(**overrides: object) -> MagicMock:
    channel = MagicMock()
    channel.id = uuid.uuid4()
    channel.tenant_id = uuid.uuid4()
    channel.type = "telegram"
    channel.status = "connected"
    channel.webhook_secret = "test-secret"
    channel.bot_token = "test-bot-token"
    channel.is_test = False
    channel.ai_enabled = True
    for key, value in overrides.items():
        setattr(channel, key, value)
    return channel


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


def _token(tenant_id: uuid.UUID | None = None) -> str:
    return create_access_token(
        user_id=uuid.uuid4(), tenant_id=tenant_id or uuid.uuid4(), role="owner"
    )


async def _post_update(
    channel_id: uuid.UUID, body: dict, secret: str | None
) -> httpx.Response:
    headers = {}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            f"/channels/telegram/{channel_id}/webhook", json=body, headers=headers
        )


_TEXT_UPDATE = {
    "update_id": 1,
    "message": {"chat": {"id": 999}, "text": "Do you ship internationally?"},
}


class TestTelegramWebhookAuth:
    async def test_rejects_unknown_channel(self) -> None:
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=None)
            response = await _post_update(uuid.uuid4(), _TEXT_UPDATE, "anything")
        assert response.status_code == 404

    async def test_rejects_missing_secret(self) -> None:
        channel = _fake_channel()
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
            response = await _post_update(channel.id, _TEXT_UPDATE, None)
        assert response.status_code == 403

    async def test_rejects_wrong_secret(self) -> None:
        channel = _fake_channel()
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
            response = await _post_update(channel.id, _TEXT_UPDATE, "wrong-secret")
        assert response.status_code == 403

    async def test_rejects_when_channel_has_no_secret_configured(self) -> None:
        # A misconfiguration must fail closed, not silently accept anything.
        channel = _fake_channel(webhook_secret=None)
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
            response = await _post_update(channel.id, _TEXT_UPDATE, "anything")
        assert response.status_code == 403


class TestTelegramWebhookHandling:
    async def test_ignores_non_text_updates(self) -> None:
        channel = _fake_channel()
        with (
            patch("app.channels.api.ChannelRepository") as mock_channel_repo_cls,
            patch("app.channels.api.process_incoming_message") as mock_task,
        ):
            mock_channel_repo_cls.return_value.get_by_id_unscoped = AsyncMock(
                return_value=channel
            )
            response = await _post_update(
                channel.id, {"update_id": 2, "message": {"chat": {"id": 999}}}, "test-secret"
            )
        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}
        mock_task.delay.assert_not_called()

    async def test_creates_conversation_and_enqueues_task_for_new_contact(self) -> None:
        channel = _fake_channel()
        new_conversation = MagicMock()
        new_conversation.id = uuid.uuid4()
        inbound_message = MagicMock()
        inbound_message.id = uuid.uuid4()
        with (
            patch("app.channels.api.ChannelRepository") as mock_channel_repo_cls,
            patch("app.channels.api.ConversationRepository") as mock_conv_repo_cls,
            patch("app.channels.api.MessageRepository") as mock_message_repo_cls,
            patch("app.channels.api.process_incoming_message") as mock_task,
            patch("app.channels.api.publish_event") as mock_publish,
        ):
            mock_channel_repo_cls.return_value.get_by_id_unscoped = AsyncMock(
                return_value=channel
            )
            mock_conv_repo_cls.return_value.get_by_external_contact = AsyncMock(
                return_value=None
            )
            mock_conv_repo_cls.return_value.add = AsyncMock(return_value=new_conversation)
            mock_message_repo_cls.return_value.add = AsyncMock(return_value=inbound_message)
            mock_publish.return_value = None

            response = await _post_update(channel.id, _TEXT_UPDATE, "test-secret")

        assert response.status_code == 200
        assert response.json() == {"status": "accepted"}
        mock_conv_repo_cls.return_value.add.assert_called_once()
        created_conversation = mock_conv_repo_cls.return_value.add.call_args.args[0]
        assert created_conversation.external_contact_id == "999"
        mock_message_repo_cls.return_value.add.assert_called_once()
        logged_message = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert logged_message.direction == "inbound"
        assert logged_message.text == "Do you ship internationally?"
        mock_task.delay.assert_called_once_with(
            str(channel.tenant_id),
            str(new_conversation.id),
            str(channel.id),
            str(inbound_message.id),
            "Do you ship internationally?",
        )
        # docs/ROADMAP.md §3.5 -- lets an already-open rail update without a
        # manual refetch.
        mock_publish.assert_called_once_with(
            channel.tenant_id,
            {
                "type": "message",
                "channel_type": channel.type,
                "conversation_id": str(new_conversation.id),
            },
        )

    async def test_reuses_existing_conversation_for_known_contact(self) -> None:
        channel = _fake_channel()
        existing_conversation = MagicMock()
        existing_conversation.id = uuid.uuid4()
        inbound_message = MagicMock()
        inbound_message.id = uuid.uuid4()
        with (
            patch("app.channels.api.ChannelRepository") as mock_channel_repo_cls,
            patch("app.channels.api.ConversationRepository") as mock_conv_repo_cls,
            patch("app.channels.api.MessageRepository") as mock_message_repo_cls,
            patch("app.channels.api.process_incoming_message") as mock_task,
            patch("app.channels.api.publish_event") as mock_publish,
        ):
            mock_channel_repo_cls.return_value.get_by_id_unscoped = AsyncMock(
                return_value=channel
            )
            mock_conv_repo_cls.return_value.get_by_external_contact = AsyncMock(
                return_value=existing_conversation
            )
            mock_message_repo_cls.return_value.add = AsyncMock(return_value=inbound_message)
            mock_publish.return_value = None

            await _post_update(channel.id, _TEXT_UPDATE, "test-secret")

        mock_conv_repo_cls.return_value.add.assert_not_called()
        mock_task.delay.assert_called_once_with(
            str(channel.tenant_id),
            str(existing_conversation.id),
            str(channel.id),
            str(inbound_message.id),
            "Do you ship internationally?",
        )


async def _list_channels(token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/channels/connected", headers=headers)


async def _update_channel_ai(
    channel_id: uuid.UUID, ai_enabled: bool, token: str | None
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.patch(
            f"/channels/{channel_id}", json={"ai_enabled": ai_enabled}, headers=headers
        )


class TestListChannels:
    async def test_rejects_missing_token(self) -> None:
        response = await _list_channels(None)
        assert response.status_code == 401

    async def test_returns_the_tenants_non_test_channels(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        channel = _fake_channel(tenant_id=tenant_id, ai_enabled=False)
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list_non_test = AsyncMock(return_value=[channel])
            response = await _list_channels(token)

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(channel.id)
        assert body[0]["type"] == "telegram"
        assert body[0]["status"] == "connected"
        assert body[0]["ai_enabled"] is False
        mock_repo_cls.return_value.list_non_test.assert_called_once_with(tenant_id)


class TestUpdateChannelAI:
    async def test_rejects_missing_token(self) -> None:
        response = await _update_channel_ai(uuid.uuid4(), False, None)
        assert response.status_code == 401

    async def test_404_when_not_found_or_wrong_tenant(self) -> None:
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _update_channel_ai(uuid.uuid4(), False, _token())
        assert response.status_code == 404

    async def test_toggles_ai_enabled_and_persists(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        channel = _fake_channel(tenant_id=tenant_id, ai_enabled=True)
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=channel)
            response = await _update_channel_ai(channel.id, False, token)

        assert response.status_code == 200
        assert response.json()["ai_enabled"] is False
        assert channel.ai_enabled is False
        mock_repo_cls.return_value.get.assert_called_once_with(tenant_id, channel.id)
