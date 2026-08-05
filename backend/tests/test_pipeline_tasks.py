import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.types import Interrupt

from app.channels.models import Channel
from app.pipeline.state import PipelineState
from app.pipeline.tasks import (
    _count_inbound_since,
    _demo_stream_daily_target,
    _follow_up_check,
    _process_incoming_message,
    _purge_stale_demo_data,
    _send_follow_up,
    _should_send_now,
    _stream_demo_dm,
    follow_up_check,
    process_incoming_message,
    purge_stale_demo_data,
    stream_demo_dm,
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
    message_id = uuid.uuid4()
    mock_inner = AsyncMock()
    with patch("app.pipeline.tasks._process_incoming_message", mock_inner):
        process_incoming_message(
            str(tenant_id),
            str(conversation_id),
            str(channel_id),
            str(message_id),
            "hello",
        )
    mock_inner.assert_called_once_with(
        tenant_id, conversation_id, channel_id, message_id, "hello"
    )


class TestProcessIncomingMessageAsync:
    async def test_interrupted_run_sends_cover_reply_and_commits(self) -> None:
        # docs/ROADMAP.md §3.1 -- an interrupted/escalated run now ALSO
        # sets draft_text (the cover reply) and already writes its own
        # internal note directly from inside the graph node, so this
        # caller-side handling is no longer special-cased: it sends/logs
        # draft_text exactly like any other reply. Only a genuinely
        # already_escalated run (see the test below) sends nothing.
        session = AsyncMock()
        channel = MagicMock()
        channel.bot_token = "test-bot-token"
        channel.type = "telegram"
        conversation = MagicMock()
        conversation.external_contact_id = "999"
        interrupt_result = {
            "__interrupt__": [Interrupt(value={"escalation_reason": "safety floor"})],
            "decision": "escalate_to_human",
            "draft_text": "Let me check on that and get back to you!",
        }
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch(
                "app.pipeline.tasks.get_checkpointer", return_value=_FakeAsyncCM(AsyncMock())
            ),
            patch(
                "app.pipeline.tasks.run_pipeline",
                AsyncMock(return_value=interrupt_result),
            ),
            patch("app.pipeline.tasks.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.tasks.ConversationRepository") as mock_conv_repo_cls,
            patch("app.pipeline.tasks.ChannelRepository") as mock_channel_repo_cls,
            patch("app.pipeline.tasks.PipelineTraceRepository") as mock_trace_repo_cls,
            patch("app.pipeline.tasks.send_message") as mock_send,
            patch("app.pipeline.tasks.publish_pipeline_events") as mock_publish,
        ):
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=channel)
            mock_trace_repo_cls.return_value.record_result = AsyncMock()
            mock_send.return_value = None
            mock_publish.return_value = None
            message_id = uuid.uuid4()
            await _process_incoming_message(
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                message_id,
                "Can you guarantee this cures allergies?",
            )

        mock_message_repo_cls.return_value.add.assert_called_once()
        logged = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert logged.direction == "outbound"
        assert logged.audience == "customer"
        assert logged.text == "Let me check on that and get back to you!"
        mock_send.assert_called_once_with(
            "test-bot-token", "999", "Let me check on that and get back to you!"
        )
        # Diagnostics are still recorded for an escalated/interrupted run --
        # the rail's badges (docs/ROADMAP.md §3.3) shouldn't go blank just
        # because the pipeline paused instead of replying.
        mock_trace_repo_cls.return_value.record_result.assert_called_once()
        assert mock_trace_repo_cls.return_value.record_result.call_args.args[2] == message_id
        # docs/ROADMAP.md §3.5 -- the escalation live-update event still
        # needs to fire even on the early-return/interrupted path, not just
        # the normal reply path below.
        mock_publish.assert_called_once()
        assert isinstance(mock_publish.call_args.args[0], PipelineState)
        assert mock_publish.call_args.args[1] is interrupt_result
        session.commit.assert_called_once()

    async def test_already_escalated_run_skips_trace_and_sends_nothing(self) -> None:
        # docs/ROADMAP.md §3.1 -- check_pending_escalation suppressed this
        # run entirely (a blocking escalation is already pending on this
        # conversation): no draft_text, no trace (which would otherwise
        # blank out a previously-good rail badge), no send.
        session = AsyncMock()
        already_escalated_result = {"already_escalated": True}
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch(
                "app.pipeline.tasks.get_checkpointer", return_value=_FakeAsyncCM(AsyncMock())
            ),
            patch(
                "app.pipeline.tasks.run_pipeline",
                AsyncMock(return_value=already_escalated_result),
            ),
            patch("app.pipeline.tasks.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.tasks.ChannelRepository") as mock_channel_repo_cls,
            patch("app.pipeline.tasks.PipelineTraceRepository") as mock_trace_repo_cls,
            patch("app.pipeline.tasks.send_message") as mock_send,
            patch("app.pipeline.tasks.publish_pipeline_events") as mock_publish,
        ):
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=None)
            mock_trace_repo_cls.return_value.record_result = AsyncMock()
            mock_publish.return_value = None
            await _process_incoming_message(
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "Any update?"
            )

        mock_message_repo_cls.return_value.add.assert_not_called()
        mock_send.assert_not_called()
        mock_trace_repo_cls.return_value.record_result.assert_not_called()
        session.commit.assert_called_once()

    async def test_sends_reply_and_logs_outbound_message(self) -> None:
        session = AsyncMock()
        channel = MagicMock()
        channel.bot_token = "test-bot-token"
        channel.type = "telegram"
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
            patch("app.pipeline.tasks.PipelineTraceRepository") as mock_trace_repo_cls,
            patch("app.pipeline.tasks.send_message") as mock_send,
            patch("app.pipeline.tasks.publish_pipeline_events") as mock_publish,
        ):
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=channel)
            mock_trace_repo_cls.return_value.record_result = AsyncMock()
            mock_send.return_value = None
            mock_publish.return_value = None

            await _process_incoming_message(
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                "Do you ship internationally?",
            )

        mock_message_repo_cls.return_value.add.assert_called_once()
        logged = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert logged.direction == "outbound"
        assert logged.text == "Sure!"
        mock_send.assert_called_once_with("test-bot-token", "999", "Sure!")
        mock_trace_repo_cls.return_value.record_result.assert_called_once()
        session.commit.assert_called_once()
        mock_publish.assert_called_once()

    async def test_delivery_failure_does_not_raise_or_block_commit(self) -> None:
        session = AsyncMock()
        channel = MagicMock()
        channel.bot_token = "test-bot-token"
        channel.type = "telegram"
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
            patch("app.pipeline.tasks.PipelineTraceRepository") as mock_trace_repo_cls,
            patch(
                "app.pipeline.tasks.send_message",
                AsyncMock(side_effect=ConnectionError("boom")),
            ),
            patch("app.pipeline.tasks.publish_pipeline_events") as mock_publish,
        ):
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=channel)
            mock_trace_repo_cls.return_value.record_result = AsyncMock()
            mock_publish.return_value = None

            await _process_incoming_message(
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                "Do you ship internationally?",
            )

        # Didn't raise (test reaching here proves it), and the DB write
        # from before the failed send still gets committed.
        session.commit.assert_called_once()

    async def test_no_send_attempt_when_channel_has_no_bot_token(self) -> None:
        session = AsyncMock()
        channel = MagicMock()
        channel.bot_token = None
        channel.type = "telegram"
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
            patch("app.pipeline.tasks.PipelineTraceRepository") as mock_trace_repo_cls,
            patch("app.pipeline.tasks.send_message") as mock_send,
            patch("app.pipeline.tasks.publish_pipeline_events") as mock_publish,
        ):
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=channel)
            mock_trace_repo_cls.return_value.record_result = AsyncMock()
            mock_publish.return_value = None

            await _process_incoming_message(
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                "Do you ship internationally?",
            )

        mock_send.assert_not_called()
        # The message is still recorded even though delivery is impossible.
        mock_message_repo_cls.return_value.add.assert_called_once()

    async def test_no_message_sent_when_channel_ai_disabled(self) -> None:
        # Channels page on/off switch, 2026-08-03 -- the pipeline run and
        # its trace/escalation side effects still happen in full; only
        # the customer-facing reply is suppressed.
        session = AsyncMock()
        channel = MagicMock()
        channel.bot_token = "test-bot-token"
        channel.type = "telegram"
        channel.ai_enabled = False
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
            patch("app.pipeline.tasks.PipelineTraceRepository") as mock_trace_repo_cls,
            patch("app.pipeline.tasks.send_message") as mock_send,
            patch("app.pipeline.tasks.publish_pipeline_events") as mock_publish,
        ):
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_conv_repo_cls.return_value.get = AsyncMock(return_value=conversation)
            mock_channel_repo_cls.return_value.get = AsyncMock(return_value=channel)
            mock_trace_repo_cls.return_value.record_result = AsyncMock()
            mock_publish.return_value = None

            await _process_incoming_message(
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                uuid.uuid4(),
                "Do you ship internationally?",
            )

        mock_message_repo_cls.return_value.add.assert_not_called()
        mock_send.assert_not_called()
        # Trace/commit/publish are unaffected -- diagnostics and dashboard
        # data keep flowing even while this channel's replies are off.
        mock_trace_repo_cls.return_value.record_result.assert_called_once()
        session.commit.assert_called_once()
        mock_publish.assert_called_once()


class TestSendFollowUp:
    async def test_no_op_when_channel_is_missing(self) -> None:
        conversation = MagicMock()
        message_repo = AsyncMock()
        channel_repo = AsyncMock()
        channel_repo.get = AsyncMock(return_value=None)

        result = await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.get_latest.assert_not_called()
        message_repo.add.assert_not_called()
        assert result is None

    async def test_no_op_when_channel_ai_is_disabled(self) -> None:
        # A follow-up nudge is itself an AI-generated auto-reply, so it's
        # covered by the same Channels-page on/off switch (2026-08-03) as
        # a real-time reply -- checked before even looking at messages.
        conversation = MagicMock()
        message_repo = AsyncMock()
        channel = MagicMock()
        channel.ai_enabled = False
        channel_repo = AsyncMock()
        channel_repo.get = AsyncMock(return_value=channel)

        result = await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.get_latest.assert_not_called()
        message_repo.add.assert_not_called()
        assert result is None

    async def test_no_op_when_conversation_has_no_messages(self) -> None:
        conversation = MagicMock()
        message_repo = AsyncMock()
        message_repo.get_latest = AsyncMock(return_value=None)
        channel = MagicMock()
        channel_repo = AsyncMock()
        channel_repo.get = AsyncMock(return_value=channel)

        result = await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.add.assert_not_called()
        channel_repo.get.assert_called_once()
        assert result is None

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
            result = await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.add.assert_called_once()
        logged = message_repo.add.call_args.args[0]
        assert logged.direction == "outbound"
        assert logged.text == "Just checking in -- still interested?"
        assert logged.conversation_id == conversation.id
        assert conversation.followed_up_at is not None
        mock_send.assert_called_once_with(
            "test-bot-token", "999", "Just checking in -- still interested?"
        )
        # docs/ROADMAP.md §3.5 -- lets the caller (_follow_up_check) know a
        # message really was written, and for which channel type, so it
        # can publish a live-update event.
        assert result == channel.type

    async def test_generation_failure_does_not_raise_or_log_a_message(self) -> None:
        conversation = MagicMock()
        last_message = MagicMock()
        last_message.text = "We ship worldwide via DHL."
        message_repo = AsyncMock()
        message_repo.get_latest = AsyncMock(return_value=last_message)
        channel = MagicMock()
        channel_repo = AsyncMock()
        channel_repo.get = AsyncMock(return_value=channel)

        with patch(
            "app.pipeline.tasks.generate_text", side_effect=ValueError("no text content")
        ):
            result = await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.add.assert_not_called()
        assert result is None

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
            result = await _send_follow_up(conversation, message_repo, channel_repo)

        message_repo.add.assert_called_once()
        assert conversation.followed_up_at is not None
        # Still returns the channel type -- the message really was written
        # (and is worth a live-update event) even though delivery failed.
        assert result == channel.type


class TestFollowUpCheckDemoMode:
    # No background job writes to a public demo's database on its own --
    # this path isn't reachable through the API at all (unlike every other
    # write path, gated by app/core/demo_mode.py's dependency), so
    # follow_up_check needs its own check before even starting the async
    # scan.
    def test_skips_entirely_when_demo_mode_enabled(self) -> None:
        with (
            patch("app.pipeline.tasks.settings.demo_mode_enabled", True),
            patch("app.pipeline.tasks._follow_up_check") as mock_inner,
        ):
            follow_up_check()
        mock_inner.assert_not_called()

    def test_runs_normally_when_demo_mode_disabled(self) -> None:
        with (
            patch("app.pipeline.tasks.settings.demo_mode_enabled", False),
            patch("app.pipeline.tasks.asyncio.run") as mock_run,
        ):
            follow_up_check()
        mock_run.assert_called_once()


class TestFollowUpCheck:
    async def test_scans_quiet_conversations_and_commits_per_conversation(self) -> None:
        session = AsyncMock()
        conversations = [MagicMock(), MagicMock()]
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch("app.pipeline.tasks.ConversationRepository") as mock_conv_repo_cls,
            patch(
                "app.pipeline.tasks._send_follow_up", AsyncMock(return_value=None)
            ) as mock_send_follow_up,
            patch("app.pipeline.tasks.publish_event") as mock_publish,
        ):
            mock_conv_repo_cls.return_value.list_quiet_unscoped = AsyncMock(
                return_value=conversations
            )
            await _follow_up_check()

        assert mock_send_follow_up.call_count == 2
        assert session.commit.call_count == 2
        # None of these follow-ups actually sent a message (the fake
        # _send_follow_up returns None throughout), so no live-update event
        # should fire either -- see the dedicated test below for the case
        # where one actually is sent.
        mock_publish.assert_not_called()

    async def test_publishes_a_message_event_only_when_a_follow_up_is_actually_sent(
        self,
    ) -> None:
        session = AsyncMock()
        sent_conversation = MagicMock()
        skipped_conversation = MagicMock()
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch("app.pipeline.tasks.ConversationRepository") as mock_conv_repo_cls,
            patch(
                "app.pipeline.tasks._send_follow_up",
                AsyncMock(side_effect=["telegram", None]),
            ),
            patch("app.pipeline.tasks.publish_event") as mock_publish,
        ):
            mock_conv_repo_cls.return_value.list_quiet_unscoped = AsyncMock(
                return_value=[sent_conversation, skipped_conversation]
            )
            await _follow_up_check()

        mock_publish.assert_called_once_with(
            sent_conversation.tenant_id,
            {
                "type": "message",
                "channel_type": "telegram",
                "conversation_id": str(sent_conversation.id),
            },
        )


class TestDemoStreamDailyTarget:
    def test_within_the_10_to_15_range(self) -> None:
        for offset in range(28):
            target = _demo_stream_daily_target(date(2026, 8, 1 + offset))
            assert 10 <= target <= 15

    def test_deterministic_for_the_same_day(self) -> None:
        day = date(2026, 8, 5)
        assert _demo_stream_daily_target(day) == _demo_stream_daily_target(day)

    def test_can_differ_across_days(self) -> None:
        targets = {_demo_stream_daily_target(date(2026, 8, d)) for d in range(1, 29)}
        assert len(targets) > 1


class TestShouldSendNow:
    def test_sends_when_behind_pace(self) -> None:
        assert _should_send_now(sent_today=2, target=12, elapsed_fraction=0.5) is True

    def test_does_not_send_when_ahead_of_pace(self) -> None:
        assert _should_send_now(sent_today=8, target=12, elapsed_fraction=0.5) is False

    def test_does_not_send_once_daily_target_is_met(self) -> None:
        assert _should_send_now(sent_today=12, target=12, elapsed_fraction=1.0) is False

    def test_never_exceeds_target_even_early_in_the_day(self) -> None:
        assert _should_send_now(sent_today=15, target=12, elapsed_fraction=0.1) is False


class TestCountInboundSince:
    async def test_returns_the_scalar_count(self) -> None:
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=7)
        result = await _count_inbound_since(session, [uuid.uuid4()], datetime.now(UTC))
        assert result == 7

    async def test_returns_zero_when_scalar_is_none(self) -> None:
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=None)
        result = await _count_inbound_since(session, [uuid.uuid4()], datetime.now(UTC))
        assert result == 0


class TestStreamDemoDmDemoMode:
    # Inverse of follow_up_check's own demo-mode check -- this job must
    # only ever run when this IS a demo deployment.
    def test_skips_when_demo_mode_disabled(self) -> None:
        with (
            patch("app.pipeline.tasks.settings.demo_mode_enabled", False),
            patch("app.pipeline.tasks._stream_demo_dm") as mock_inner,
        ):
            stream_demo_dm()
        mock_inner.assert_not_called()

    def test_runs_when_demo_mode_enabled(self) -> None:
        with (
            patch("app.pipeline.tasks.settings.demo_mode_enabled", True),
            patch("app.pipeline.tasks.asyncio.run") as mock_run,
        ):
            stream_demo_dm()
        mock_run.assert_called_once()


class TestStreamDemoDm:
    async def test_no_op_when_no_tenants_exist(self) -> None:
        session = AsyncMock()
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch("app.pipeline.tasks.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.tasks.ingest_inbound_message") as mock_ingest,
        ):
            mock_tenant_repo_cls.return_value.list_with_owner_unscoped = AsyncMock(
                return_value=[]
            )
            await _stream_demo_dm()
        mock_ingest.assert_not_called()

    async def test_no_op_when_pacing_says_not_yet(self) -> None:
        session = AsyncMock()
        tenant = MagicMock()
        tenant.id = uuid.uuid4()
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch("app.pipeline.tasks.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.tasks._count_inbound_since", AsyncMock(return_value=99)),
            patch("app.pipeline.tasks._should_send_now", return_value=False),
            patch("app.pipeline.tasks.ingest_inbound_message") as mock_ingest,
        ):
            mock_tenant_repo_cls.return_value.list_with_owner_unscoped = AsyncMock(
                return_value=[(tenant, MagicMock())]
            )
            await _stream_demo_dm()
        mock_ingest.assert_not_called()

    async def test_reuses_an_existing_demo_stream_channel(self) -> None:
        session = AsyncMock()
        tenant = MagicMock()
        tenant.id = uuid.uuid4()
        existing_channel = MagicMock()
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch("app.pipeline.tasks.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.tasks._count_inbound_since", AsyncMock(return_value=0)),
            patch("app.pipeline.tasks._should_send_now", return_value=True),
            patch("app.pipeline.tasks.ChannelRepository") as mock_channel_repo_cls,
            patch("app.pipeline.tasks.ingest_inbound_message", AsyncMock()) as mock_ingest,
        ):
            mock_tenant_repo_cls.return_value.list_with_owner_unscoped = AsyncMock(
                return_value=[(tenant, MagicMock())]
            )
            mock_channel_repo_cls.return_value.get_demo_stream_channel = AsyncMock(
                return_value=existing_channel
            )
            await _stream_demo_dm()

        mock_channel_repo_cls.return_value.add.assert_not_called()
        mock_ingest.assert_called_once()
        assert mock_ingest.call_args.args[0] is existing_channel
        external_contact_id = mock_ingest.call_args.args[1]
        assert external_contact_id.startswith("demo-")
        text = mock_ingest.call_args.args[2]
        assert isinstance(text, str) and text

    async def test_creates_a_channel_lazily_when_none_exists(self) -> None:
        session = AsyncMock()
        tenant = MagicMock()
        tenant.id = uuid.uuid4()
        new_channel = MagicMock()
        with (
            patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)),
            patch("app.pipeline.tasks.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.tasks._count_inbound_since", AsyncMock(return_value=0)),
            patch("app.pipeline.tasks._should_send_now", return_value=True),
            patch("app.pipeline.tasks.ChannelRepository") as mock_channel_repo_cls,
            patch("app.pipeline.tasks.ingest_inbound_message", AsyncMock()) as mock_ingest,
        ):
            mock_tenant_repo_cls.return_value.list_with_owner_unscoped = AsyncMock(
                return_value=[(tenant, MagicMock())]
            )
            mock_channel_repo_cls.return_value.get_demo_stream_channel = AsyncMock(
                return_value=None
            )
            mock_channel_repo_cls.return_value.add = AsyncMock(return_value=new_channel)
            await _stream_demo_dm()

        mock_channel_repo_cls.return_value.add.assert_called_once()
        created = mock_channel_repo_cls.return_value.add.call_args.args[0]
        assert isinstance(created, Channel)
        assert created.tenant_id == tenant.id
        assert created.is_test is False
        assert created.bot_token is None
        mock_ingest.assert_called_once()
        assert mock_ingest.call_args.args[0] is new_channel


class TestPurgeStaleDemoDataDemoMode:
    def test_skips_when_demo_mode_disabled(self) -> None:
        with (
            patch("app.pipeline.tasks.settings.demo_mode_enabled", False),
            patch("app.pipeline.tasks._purge_stale_demo_data") as mock_inner,
        ):
            purge_stale_demo_data()
        mock_inner.assert_not_called()

    def test_runs_when_demo_mode_enabled(self) -> None:
        with (
            patch("app.pipeline.tasks.settings.demo_mode_enabled", True),
            patch("app.pipeline.tasks.asyncio.run") as mock_run,
        ):
            purge_stale_demo_data()
        mock_run.assert_called_once()


class TestPurgeStaleDemoData:
    async def test_returns_zero_and_deletes_nothing_when_none_are_stale(self) -> None:
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.scalars = AsyncMock(return_value=mock_result)
        with patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)):
            result = await _purge_stale_demo_data()
        assert result == 0
        session.execute.assert_not_called()
        session.commit.assert_not_called()

    async def test_deletes_stale_conversations_and_children_in_fk_safe_order(self) -> None:
        stale_ids = [uuid.uuid4(), uuid.uuid4()]
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = stale_ids
        session.scalars = AsyncMock(return_value=mock_result)
        with patch("app.pipeline.tasks.async_session", return_value=_FakeAsyncCM(session)):
            result = await _purge_stale_demo_data()

        assert result == 2
        session.commit.assert_called_once()
        # PipelineTrace (references message_id, so first), Message
        # (can reference escalation_id, so before Escalation), Escalation,
        # Lead, Conversation last -- see the function's own comment for
        # why this order matters (no model here declares ondelete=CASCADE).
        tables = [call.args[0].table.name for call in session.execute.call_args_list]
        assert tables == [
            "pipeline_traces",
            "messages",
            "escalations",
            "leads",
            "conversations",
        ]
