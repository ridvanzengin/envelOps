import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.main import app


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


def _token(tenant_id: uuid.UUID) -> str:
    return create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")


async def _send_message(token: str, channel_type: str, text: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/test/conversations/messages",
            json={
                "channel_type": channel_type,
                "external_contact_id": "session-1",
                "text": text,
            },
            headers={"Authorization": f"Bearer {token}"},
        )


class TestSendTestMessagePublishesLiveUpdateEvents:
    async def test_publishes_inbound_then_pipeline_events(self) -> None:
        # docs/ROADMAP.md §3.5 -- Test Console runs the pipeline
        # synchronously (no Celery hand-off), so both the inbound-message
        # publish and the pipeline-outcome publish happen in this one
        # request, right after each of the two commits this endpoint makes
        # (CLAUDE.md's checkpointer-commit-before-invoke rule is why there
        # are two commits at all).
        tenant_id = uuid.uuid4()
        channel = MagicMock()
        channel.id = uuid.uuid4()
        channel.tenant_id = tenant_id
        conversation = MagicMock()
        conversation.id = uuid.uuid4()
        inbound_message = MagicMock()
        inbound_message.id = uuid.uuid4()

        with (
            patch("app.test_console.api.ChannelRepository") as mock_channel_repo_cls,
            patch("app.test_console.api.ConversationRepository") as mock_conv_repo_cls,
            patch("app.test_console.api.MessageRepository") as mock_message_repo_cls,
            patch("app.test_console.api.PipelineTraceRepository") as mock_trace_repo_cls,
            patch("app.test_console.api.get_checkpointer") as mock_get_checkpointer,
            patch(
                "app.test_console.api.run_pipeline",
                AsyncMock(return_value={"decision": "keep_chatting", "draft_text": "Sure!"}),
            ),
            patch("app.test_console.api.publish_event") as mock_publish_event,
            patch("app.test_console.api.publish_pipeline_events") as mock_publish_pipeline,
        ):
            mock_channel_repo_cls.return_value.get_test_channel = AsyncMock(
                return_value=channel
            )
            mock_conv_repo_cls.return_value.get_by_external_contact = AsyncMock(
                return_value=conversation
            )
            mock_message_repo_cls.return_value.add = AsyncMock(
                side_effect=[inbound_message, MagicMock()]
            )
            mock_trace_repo_cls.return_value.record_result = AsyncMock()
            mock_trace_repo_cls.return_value.list_by_conversation = AsyncMock(return_value=[])
            mock_message_repo_cls.return_value.list_by_conversation = AsyncMock(
                return_value=[]
            )

            class _FakeCheckpointerCM:
                async def __aenter__(self) -> object:
                    return AsyncMock()

                async def __aexit__(self, *args: object) -> bool:
                    return False

            mock_get_checkpointer.return_value = _FakeCheckpointerCM()
            mock_publish_event.return_value = None
            mock_publish_pipeline.return_value = None

            response = await _send_message(_token(tenant_id), "telegram", "Do you ship?")

        assert response.status_code == 200
        mock_publish_event.assert_called_once_with(
            tenant_id,
            {
                "type": "message",
                "channel_type": "telegram",
                "conversation_id": str(conversation.id),
            },
        )
        mock_publish_pipeline.assert_called_once()
        published_state = mock_publish_pipeline.call_args.args[0]
        assert published_state.tenant_id == tenant_id
        assert published_state.conversation_id == conversation.id
