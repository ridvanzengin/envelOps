import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.core.llm import AiProviderError
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


class TestSendTestMessageAiProviderFailure:
    # A Gemini failure (rate limit, network, auth -- app/core/llm.py's
    # AiProviderError) propagates up through run_pipeline uncaught, same
    # as any other pipeline node exception -- app/main.py's global
    # exception handler is what turns it into a friendly 502 instead of a
    # raw 500. Covers the real (non-demo) path only -- _send_test_message_demo
    # runs the identical run_pipeline call, so the same handler applies
    # there too, nothing path-specific to re-test.
    async def test_returns_friendly_502_instead_of_raw_error(self) -> None:
        tenant_id = uuid.uuid4()
        channel = MagicMock()
        channel.id = uuid.uuid4()
        conversation = MagicMock()
        conversation.id = uuid.uuid4()
        inbound_message = MagicMock()
        inbound_message.id = uuid.uuid4()

        with (
            patch("app.test_console.api.ChannelRepository") as mock_channel_repo_cls,
            patch("app.test_console.api.ConversationRepository") as mock_conv_repo_cls,
            patch("app.test_console.api.MessageRepository") as mock_message_repo_cls,
            patch("app.test_console.api.get_checkpointer") as mock_get_checkpointer,
            patch(
                "app.test_console.api.run_pipeline",
                AsyncMock(side_effect=AiProviderError("429 RESOURCE_EXHAUSTED")),
            ),
            patch("app.test_console.api.publish_event", AsyncMock()),
        ):
            mock_channel_repo_cls.return_value.get_test_channel = AsyncMock(
                return_value=channel
            )
            mock_conv_repo_cls.return_value.get_by_external_contact = AsyncMock(
                return_value=conversation
            )
            mock_message_repo_cls.return_value.add = AsyncMock(return_value=inbound_message)

            class _FakeCheckpointerCM:
                async def __aenter__(self) -> object:
                    return AsyncMock()

                async def __aexit__(self, *args: object) -> bool:
                    return False

            mock_get_checkpointer.return_value = _FakeCheckpointerCM()

            response = await _send_message(_token(tenant_id), "telegram", "Do you ship?")

        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "temporarily unavailable" in detail
        # The raw exception text must never reach the client -- that's the
        # whole point of the global handler, not just that *some* error
        # came back.
        assert "RESOURCE_EXHAUSTED" not in detail


class TestSendTestMessageDemoMode:
    # demo_mode_enabled runs the real pipeline (mocked here, same as every
    # other test in this file) but must never touch a Channel/Conversation/
    # Message/PipelineTrace repository at all -- app/test_console/api.py's
    # _send_test_message_demo, a completely separate code path from the
    # one exercised above.
    @pytest.fixture(autouse=True)
    def _clear_demo_state(self) -> object:
        from app.test_console.api import _demo_conversation_messages

        _demo_conversation_messages.clear()
        yield
        _demo_conversation_messages.clear()

    async def test_runs_pipeline_without_touching_any_repository(self) -> None:
        tenant_id = uuid.uuid4()
        session = AsyncMock()
        # session.add() is sync in real SQLAlchemy -- AsyncMock's blanket
        # auto-mocking would otherwise make it return an unawaited
        # coroutine (a harmless warning, not a real bug, but worth
        # matching the real method's shape).
        session.add = MagicMock()
        with (
            patch("app.test_console.api.settings.demo_mode_enabled", True),
            patch("app.core.db.get_session", return_value=session),
            patch("app.test_console.api.ChannelRepository") as mock_channel_repo_cls,
            patch("app.test_console.api.ConversationRepository") as mock_conv_repo_cls,
            patch("app.test_console.api.MessageRepository") as mock_message_repo_cls,
            patch("app.test_console.api.PipelineTraceRepository") as mock_trace_repo_cls,
            patch(
                "app.test_console.api.run_pipeline",
                AsyncMock(
                    return_value={
                        "decision": "keep_chatting",
                        "draft_text": "Sure, we ship worldwide!",
                        "detected_intent": "knowledge_question",
                        "lead_score": "warm",
                    }
                ),
            ) as mock_run_pipeline,
        ):
            app.dependency_overrides[get_session] = lambda: session
            try:
                response = await _send_message(_token(tenant_id), "telegram", "Do you ship?")
            finally:
                app.dependency_overrides[get_session] = lambda: AsyncMock()

        assert response.status_code == 200
        body = response.json()
        assert len(body["messages"]) == 2
        assert body["messages"][0]["direction"] == "inbound"
        assert body["messages"][0]["diagnostics"]["detected_intent"] == "knowledge_question"
        assert body["messages"][1]["direction"] == "outbound"
        assert body["messages"][1]["text"] == "Sure, we ship worldwide!"

        # The real pipeline genuinely ran...
        mock_run_pipeline.assert_called_once()
        # ...but nothing was persisted: no repository class was ever
        # touched (the demo path inserts a real Channel/Conversation
        # directly via session.add() + session.flush() -- see
        # _send_test_message_demo's own docstring for why: graph.py's own
        # nodes insert Lead/Escalation rows with a real foreign key to
        # conversation_id, and Postgres enforces that at INSERT time, not
        # commit time -- but never via commit(), which is what would make
        # any of it durable.
        mock_channel_repo_cls.assert_not_called()
        mock_conv_repo_cls.assert_not_called()
        mock_message_repo_cls.assert_not_called()
        mock_trace_repo_cls.assert_not_called()
        assert session.commit.call_count == 0
        assert session.flush.call_count == 2

    async def test_second_message_in_same_session_continues_the_conversation(self) -> None:
        tenant_id = uuid.uuid4()
        session = AsyncMock()
        session.add = MagicMock()
        with (
            patch("app.test_console.api.settings.demo_mode_enabled", True),
            patch(
                "app.test_console.api.run_pipeline",
                AsyncMock(return_value={"decision": "keep_chatting", "draft_text": "Hi!"}),
            ),
        ):
            app.dependency_overrides[get_session] = lambda: session
            try:
                token = _token(tenant_id)
                first = await _send_message(token, "telegram", "Hello")
                second = await _send_message(token, "telegram", "Still there?")
            finally:
                app.dependency_overrides[get_session] = lambda: AsyncMock()

        assert first.status_code == second.status_code == 200
        # Same (tenant, channel_type, session) -> same deterministic
        # thread_id, and the second response's history includes both
        # exchanges, not just its own -- proving conversation continuity
        # comes from the in-memory store, not a persisted Conversation row.
        assert first.json()["conversation_id"] == second.json()["conversation_id"]
        assert len(second.json()["messages"]) == 4
