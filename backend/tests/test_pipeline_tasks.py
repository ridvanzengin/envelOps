import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.pipeline.tasks import (
    _follow_up_check,
    _process_incoming_message,
    _send_follow_up,
    process_incoming_message,
)


class _FakeAsyncCM:
    """Stands in for async_session()/get_checkpointer() -- both are called
    as plain functions returning something usable in `async with`, not
    awaited directly."""

    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, *args: object) -> bool:
        return False


def test_process_incoming_message_parses_uuids_and_delegates() -> None:
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    mock_inner = AsyncMock()
    with patch("app.pipeline.tasks._process_incoming_message", mock_inner):
        process_incoming_message(
            str(tenant_id), str(conversation_id), str(channel_id), "hello"
        )
    mock_inner.assert_called_once_with(tenant_id, conversation_id, channel_id, "hello")


class TestProcessIncomingMessageAsync:
    async def test_interrupted_run_commits_without_sending_anything(self) -> None:
        session = AsyncMock()
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch(
                "app.pipeline.tasks.get_checkpointer", return_value=_FakeAsyncCM(AsyncMock())
            ),
            patch(
                "app.pipeline.tasks.run_pipeline",
                AsyncMock(return_value={"__interrupt__": []}),
            ),
            patch("app.pipeline.tasks.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.tasks.send_message") as mock_send,
        ):
            await _process_incoming_message(
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                "Can you guarantee this cures allergies?",
            )

        mock_message_repo_cls.return_value.add.assert_not_called()
        mock_send.assert_not_called()
        session.commit.assert_called_once()

    async def test_sends_reply_and_logs_outbound_message(self) -> None:
        session = AsyncMock()
        channel = MagicMock()
        channel.bot_token = "test-bot-token"
        conversation = MagicMock()
        conversation.external_contact_id = "999"
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch(
                "app.pipeline.tasks.get_checkpointer", return_value=_FakeAsyncCM(AsyncMock())
            ),
            patch(
                "app.pipeline.tasks.run_pipeline",
                AsyncMock(return_value={"decision": "keep_chatting", "draft_text": "Sure!"}),
            ),
            patch("app.pipeline.tasks.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.tasks.ConversationRepository") as mock_conv_repo_cls,
            patch("app.pipeline.tasks.ChannelRepository") as mock_channel_repo_cls,
            patch("app.pipeline.tasks.send_message") as mock_send,
        ):
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=channel)
            mock_send.return_value = None

            await _process_incoming_message(
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "Do you ship internationally?"
            )

        mock_message_repo_cls.return_value.add.assert_called_once()
        logged = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert logged.direction == "outbound"
        assert logged.text == "Sure!"
        mock_send.assert_called_once_with("test-bot-token", "999", "Sure!")
        session.commit.assert_called_once()

    async def test_delivery_failure_does_not_raise_or_block_commit(self) -> None:
        session = AsyncMock()
        channel = MagicMock()
        channel.bot_token = "test-bot-token"
        conversation = MagicMock()
        conversation.external_contact_id = "999"
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch(
                "app.pipeline.tasks.get_checkpointer", return_value=_FakeAsyncCM(AsyncMock())
            ),
            patch(
                "app.pipeline.tasks.run_pipeline",
                AsyncMock(return_value={"decision": "keep_chatting", "draft_text": "Sure!"}),
            ),
            patch("app.pipeline.tasks.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.tasks.ConversationRepository") as mock_conv_repo_cls,
            patch("app.pipeline.tasks.ChannelRepository") as mock_channel_repo_cls,
            patch(
                "app.pipeline.tasks.send_message",
                AsyncMock(side_effect=ConnectionError("boom")),
            ),
        ):
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=channel)

            await _process_incoming_message(
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "Do you ship internationally?"
            )

        # Didn't raise (test reaching here proves it), and the DB write
        # from before the failed send still gets committed.
        session.commit.assert_called_once()

    async def test_no_send_attempt_when_channel_has_no_bot_token(self) -> None:
        session = AsyncMock()
        channel = MagicMock()
        channel.bot_token = None
        conversation = MagicMock()
        conversation.external_contact_id = "999"
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch(
                "app.pipeline.tasks.get_checkpointer", return_value=_FakeAsyncCM(AsyncMock())
            ),
            patch(
                "app.pipeline.tasks.run_pipeline",
                AsyncMock(return_value={"decision": "keep_chatting", "draft_text": "Sure!"}),
            ),
            patch("app.pipeline.tasks.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.tasks.ConversationRepository") as mock_conv_repo_cls,
            patch("app.pipeline.tasks.ChannelRepository") as mock_channel_repo_cls,
            patch("app.pipeline.tasks.send_message") as mock_send,
        ):
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=channel)

            await _process_incoming_message(
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "Do you ship internationally?"
            )

        mock_send.assert_not_called()
        # The message is still recorded even though delivery is impossible.
        mock_message_repo_cls.return_value.add.assert_called_once()


class TestSendFollowUp:
    async def test_no_op_when_conversation_has_no_messages(self) -> None:
        conversation = MagicMock()
        message_repo = AsyncMock()
        message_repo.get_latest = AsyncMock(return_value=None)
        channel_repo = AsyncMock()

        await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.add.assert_not_called()
        channel_repo.get.assert_not_called()

    async def test_generates_logs_and_sends_a_follow_up(self) -> None:
        conversation = MagicMock()
        conversation.tenant_id = uuid.uuid4()
        conversation.id = uuid.uuid4()
        conversation.external_contact_id = "999"
        conversation.followed_up_at = None
        last_message = MagicMock()
        last_message.text = "We ship worldwide via DHL."
        message_repo = AsyncMock()
        message_repo.get_latest = AsyncMock(return_value=last_message)
        channel = MagicMock()
        channel.bot_token = "test-bot-token"
        channel_repo = AsyncMock()
        channel_repo.get = AsyncMock(return_value=channel)

        with (
            patch(
                "app.pipeline.tasks.generate_text",
                return_value="Just checking in -- still interested?",
            ),
            patch("app.pipeline.tasks.send_message", AsyncMock()) as mock_send,
        ):
            await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.add.assert_called_once()
        logged = message_repo.add.call_args.args[0]
        assert logged.direction == "outbound"
        assert logged.text == "Just checking in -- still interested?"
        assert logged.conversation_id == conversation.id
        assert conversation.followed_up_at is not None
        mock_send.assert_called_once_with(
            "test-bot-token", "999", "Just checking in -- still interested?"
        )

    async def test_generation_failure_does_not_raise_or_log_a_message(self) -> None:
        conversation = MagicMock()
        last_message = MagicMock()
        last_message.text = "We ship worldwide via DHL."
        message_repo = AsyncMock()
        message_repo.get_latest = AsyncMock(return_value=last_message)
        channel_repo = AsyncMock()

        with patch(
            "app.pipeline.tasks.generate_text", side_effect=ValueError("no text content")
        ):
            await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.add.assert_not_called()
        channel_repo.get.assert_not_called()

    async def test_delivery_failure_does_not_raise_and_still_marks_followed_up(self) -> None:
        conversation = MagicMock()
        conversation.followed_up_at = None
        last_message = MagicMock()
        last_message.text = "We ship worldwide via DHL."
        message_repo = AsyncMock()
        message_repo.get_latest = AsyncMock(return_value=last_message)
        channel = MagicMock()
        channel.bot_token = "test-bot-token"
        channel_repo = AsyncMock()
        channel_repo.get = AsyncMock(return_value=channel)

        with (
            patch("app.pipeline.tasks.generate_text", return_value="Still there?"),
            patch(
                "app.pipeline.tasks.send_message",
                AsyncMock(side_effect=ConnectionError("boom")),
            ),
        ):
            await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.add.assert_called_once()
        assert conversation.followed_up_at is not None


class TestFollowUpCheck:
    async def test_scans_quiet_conversations_and_commits_per_conversation(self) -> None:
        session = AsyncMock()
        conversations = [MagicMock(), MagicMock()]
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch("app.pipeline.tasks.ConversationRepository") as mock_conv_repo_cls,
            patch("app.pipeline.tasks._send_follow_up", AsyncMock()) as mock_send_follow_up,
        ):
            mock_conv_repo_cls.return_value.list_quiet_unscoped = AsyncMock(
                return_value=conversations
            )
            await _follow_up_check()

        assert mock_send_follow_up.call_count == 2
        assert session.commit.call_count == 2
