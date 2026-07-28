import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.db import get_session
from app.main import app


def _fake_channel(**overrides: object) -> MagicMock:
    channel = MagicMock()
    channel.id = uuid.uuid4()
    channel.tenant_id = uuid.uuid4()
    channel.type = "telegram"
    channel.webhook_secret = "test-secret"
    channel.bot_token = "test-bot-token"
    for key, value in overrides.items():
        setattr(channel, key, value)
    return channel


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


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
        ):
            mock_channel_repo_cls.return_value.get_by_id_unscoped = AsyncMock(
                return_value=channel
            )
            mock_conv_repo_cls.return_value.get_by_external_contact = AsyncMock(
                return_value=None
            )
            mock_conv_repo_cls.return_value.add = AsyncMock(return_value=new_conversation)
            mock_message_repo_cls.return_value.add = AsyncMock(return_value=inbound_message)

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
        ):
            mock_channel_repo_cls.return_value.get_by_id_unscoped = AsyncMock(
                return_value=channel
            )
            mock_conv_repo_cls.return_value.get_by_external_contact = AsyncMock(
                return_value=existing_conversation
            )
            mock_message_repo_cls.return_value.add = AsyncMock(return_value=inbound_message)

            await _post_update(channel.id, _TEXT_UPDATE, "test-secret")

        mock_conv_repo_cls.return_value.add.assert_not_called()
        mock_task.delay.assert_called_once_with(
            str(channel.tenant_id),
            str(existing_conversation.id),
            str(channel.id),
            str(inbound_message.id),
            "Do you ship internationally?",
        )
