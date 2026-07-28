import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.main import app


def _fake_conversation(tenant_id: uuid.UUID, **overrides: object) -> MagicMock:
    conversation = MagicMock()
    conversation.id = uuid.uuid4()
    conversation.tenant_id = tenant_id
    conversation.external_contact_id = "999"
    conversation.status = "open"
    for key, value in overrides.items():
        setattr(conversation, key, value)
    return conversation


def _fake_message(**overrides: object) -> MagicMock:
    message = MagicMock()
    message.id = uuid.uuid4()
    message.direction = "inbound"
    message.text = "Do you ship internationally?"
    message.created_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(message, key, value)
    return message


def _fake_channel(**overrides: object) -> MagicMock:
    channel = MagicMock()
    channel.type = "telegram"
    channel.is_test = False
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


async def _list_conversations(token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/conversations", headers=headers)


async def _list_messages(conversation_id: uuid.UUID, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/conversations/{conversation_id}/messages", headers=headers)


class TestListConversations:
    async def test_rejects_missing_token(self) -> None:
        response = await _list_conversations(None)
        assert response.status_code == 401

    async def test_returns_conversations_with_last_message_preview(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        conversation = _fake_conversation(tenant_id)
        message = _fake_message(text="Yes, we ship worldwide!")
        channel = _fake_channel()
        with patch("app.conversations.api.ConversationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list_with_last_message = AsyncMock(
                return_value=[(conversation, message, channel)]
            )
            response = await _list_conversations(token)

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(conversation.id)
        assert body[0]["last_message_text"] == "Yes, we ship worldwide!"
        assert body[0]["channel_type"] == "telegram"
        assert body[0]["is_test"] is False
        mock_repo_cls.return_value.list_with_last_message.assert_called_once_with(
            tenant_id, None
        )

    async def test_handles_a_conversation_with_no_messages(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        conversation = _fake_conversation(tenant_id)
        channel = _fake_channel()
        with patch("app.conversations.api.ConversationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list_with_last_message = AsyncMock(
                return_value=[(conversation, None, channel)]
            )
            response = await _list_conversations(token)

        assert response.status_code == 200
        body = response.json()
        assert body[0]["last_message_text"] is None
        assert body[0]["last_message_at"] is None


class TestListMessages:
    async def test_rejects_missing_token(self) -> None:
        response = await _list_messages(uuid.uuid4(), None)
        assert response.status_code == 401

    async def test_404_when_not_found_or_wrong_tenant(self) -> None:
        with patch("app.conversations.api.ConversationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _list_messages(uuid.uuid4(), _token())
        assert response.status_code == 404

    async def test_returns_messages_in_thread_order(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        conversation = _fake_conversation(tenant_id)
        first = _fake_message(direction="inbound", text="Do you ship internationally?")
        second = _fake_message(direction="outbound", text="Yes, we ship worldwide!")
        with (
            patch("app.conversations.api.ConversationRepository") as mock_conv_repo_cls,
            patch("app.conversations.api.MessageRepository") as mock_message_repo_cls,
        ):
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_message_repo_cls.return_value.list_by_conversation = AsyncMock(
                return_value=[first, second]
            )
            response = await _list_messages(conversation.id, token)

        assert response.status_code == 200
        body = response.json()
        assert [m["text"] for m in body] == [
            "Do you ship internationally?",
            "Yes, we ship worldwide!",
        ]
        mock_message_repo_cls.return_value.list_by_conversation.assert_called_once_with(
            tenant_id, conversation.id
        )
