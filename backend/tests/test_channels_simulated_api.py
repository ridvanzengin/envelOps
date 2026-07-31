import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.db import get_session
from app.main import app

_SECRET_HEADER = "X-EnvelOps-Simulated-Webhook-Secret"


def _fake_channel(**overrides: object) -> MagicMock:
    channel = MagicMock()
    channel.id = uuid.uuid4()
    channel.tenant_id = uuid.uuid4()
    channel.type = "instagram"
    channel.webhook_secret = "test-secret"
    channel.bot_token = None
    for key, value in overrides.items():
        setattr(channel, key, value)
    return channel


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


async def _post(path: str, body: dict, secret: str | None) -> httpx.Response:
    headers = {}
    if secret is not None:
        headers[_SECRET_HEADER] = secret
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body, headers=headers)


_INSTAGRAM_MESSAGE = {"sender": {"id": "ig-user-1"}, "message": {"text": "Hi there!"}}


class TestSimulatedWebhookAuth:
    """The auth check itself lives entirely in the one shared
    _simulated_webhook function, identical for all 4 platforms -- tested
    thoroughly once here (via Instagram) rather than 4 times over."""

    async def test_rejects_unknown_channel(self) -> None:
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=None)
            response = await _post(
                f"/channels/instagram/{uuid.uuid4()}/webhook", _INSTAGRAM_MESSAGE, "anything"
            )
        assert response.status_code == 404

    async def test_rejects_channel_of_the_wrong_type(self) -> None:
        channel = _fake_channel(type="whatsapp")  # exists, but not an instagram channel
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
            response = await _post(
                f"/channels/instagram/{channel.id}/webhook", _INSTAGRAM_MESSAGE, "test-secret"
            )
        assert response.status_code == 404

    async def test_rejects_missing_secret(self) -> None:
        channel = _fake_channel()
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
            response = await _post(
                f"/channels/instagram/{channel.id}/webhook", _INSTAGRAM_MESSAGE, None
            )
        assert response.status_code == 403

    async def test_rejects_wrong_secret(self) -> None:
        channel = _fake_channel()
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
            response = await _post(
                f"/channels/instagram/{channel.id}/webhook", _INSTAGRAM_MESSAGE, "wrong"
            )
        assert response.status_code == 403

    async def test_rejects_when_channel_has_no_secret_configured(self) -> None:
        channel = _fake_channel(webhook_secret=None)
        with patch("app.channels.api.ChannelRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
            response = await _post(
                f"/channels/instagram/{channel.id}/webhook", _INSTAGRAM_MESSAGE, "anything"
            )
        assert response.status_code == 403


async def _assert_ingests(
    platform: str, channel_type: str, body: dict, expected_contact_id: str, expected_text: str
) -> None:
    channel = _fake_channel(type=channel_type)
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
        mock_channel_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
        mock_conv_repo_cls.return_value.get_by_external_contact = AsyncMock(return_value=None)
        mock_conv_repo_cls.return_value.add = AsyncMock(return_value=new_conversation)
        mock_message_repo_cls.return_value.add = AsyncMock(return_value=inbound_message)
        mock_publish.return_value = None

        path = f"/channels/{platform}/{channel.id}/webhook"
        response = await _post(path, body, "test-secret")

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    created_conversation = mock_conv_repo_cls.return_value.add.call_args.args[0]
    assert created_conversation.external_contact_id == expected_contact_id
    logged_message = mock_message_repo_cls.return_value.add.call_args.args[0]
    assert logged_message.direction == "inbound"
    assert logged_message.text == expected_text
    mock_task.delay.assert_called_once_with(
        str(channel.tenant_id),
        str(new_conversation.id),
        str(channel.id),
        str(inbound_message.id),
        expected_text,
    )


async def _assert_ignores_blank(platform: str, channel_type: str, body: dict) -> None:
    channel = _fake_channel(type=channel_type)
    with (
        patch("app.channels.api.ChannelRepository") as mock_channel_repo_cls,
        patch("app.channels.api.process_incoming_message") as mock_task,
    ):
        mock_channel_repo_cls.return_value.get_by_id_unscoped = AsyncMock(return_value=channel)
        path = f"/channels/{platform}/{channel.id}/webhook"
        response = await _post(path, body, "test-secret")
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    mock_task.delay.assert_not_called()


class TestInstagramWebhook:
    async def test_ingests_a_real_message(self) -> None:
        await _assert_ingests(
            "instagram",
            "instagram",
            {"sender": {"id": "ig-user-1"}, "message": {"text": "Hi there!"}},
            "ig-user-1",
            "Hi there!",
        )

    async def test_ignores_a_non_text_event(self) -> None:
        await _assert_ignores_blank("instagram", "instagram", {"sender": {"id": "ig-user-1"}})


class TestFacebookWebhook:
    async def test_ingests_a_real_message(self) -> None:
        await _assert_ingests(
            "facebook",
            "facebook",
            {"sender": {"id": "fb-user-1"}, "message": {"text": "Hello!"}},
            "fb-user-1",
            "Hello!",
        )

    async def test_ignores_a_non_text_event(self) -> None:
        await _assert_ignores_blank("facebook", "facebook", {"sender": {"id": "fb-user-1"}})


class TestWhatsAppWebhook:
    async def test_ingests_a_real_message(self) -> None:
        await _assert_ingests(
            "whatsapp",
            "whatsapp",
            {"from": "+15551234567", "text": {"body": "Order status?"}},
            "+15551234567",
            "Order status?",
        )

    async def test_ignores_a_non_text_event(self) -> None:
        await _assert_ignores_blank("whatsapp", "whatsapp", {"from": "+15551234567"})


class TestEmailWebhook:
    async def test_ingests_a_real_message(self) -> None:
        await _assert_ingests(
            "email",
            "email",
            {"from_address": "customer@example.com", "subject": "Question", "text": "Hi!"},
            "customer@example.com",
            "Hi!",
        )

    async def test_ignores_blank_text(self) -> None:
        await _assert_ignores_blank(
            "email", "email", {"from_address": "customer@example.com", "text": ""}
        )


class TestSimulatedWebhookReusesConversation:
    async def test_reuses_existing_conversation_for_known_contact(self) -> None:
        channel = _fake_channel(type="instagram")
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

            await _post(
                f"/channels/instagram/{channel.id}/webhook", _INSTAGRAM_MESSAGE, "test-secret"
            )

        mock_conv_repo_cls.return_value.add.assert_not_called()
        mock_task.delay.assert_called_once_with(
            str(channel.tenant_id),
            str(existing_conversation.id),
            str(channel.id),
            str(inbound_message.id),
            "Hi there!",
        )
