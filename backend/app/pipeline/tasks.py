"""Celery task that runs the pipeline for one inbound message
(docs/ARCHITECTURE.md §8's `process_incoming_message`) — the bridge between
channel ingestion (app/channels/api.py) and the pipeline
(app/pipeline/runner.py). Celery tasks are plain sync callables; the
pipeline is async throughout (async DB session, async checkpointer), so
this bridges via `asyncio.run()` once per task invocation — a standard,
accepted pattern for running async code inside a sync Celery worker, not a
workaround.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from app.channels.repository import ChannelRepository
from app.channels.telegram_client import send_message
from app.conversations.models import Conversation, Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.db import async_session
from app.core.events import publish_event
from app.core.llm import generate_text
from app.pipeline.repository import PipelineTraceRepository
from app.pipeline.runner import get_checkpointer, publish_pipeline_events, run_pipeline
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


@celery_app.task(name="process_incoming_message")
def process_incoming_message(
    tenant_id: str,
    conversation_id: str,
    channel_id: str,
    message_id: str,
    incoming_text: str,
) -> None:
    asyncio.run(
        _process_incoming_message(
            uuid.UUID(tenant_id),
            uuid.UUID(conversation_id),
            uuid.UUID(channel_id),
            uuid.UUID(message_id),
            incoming_text,
        )
    )


async def _process_incoming_message(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    channel_id: uuid.UUID,
    message_id: uuid.UUID,
    incoming_text: str,
) -> None:
    async with async_session() as session:
        # Fetched up front (not just later for bot_token/send below) so its
        # type can drive channel_type -- keep_chatting/book_or_checkout's
        # reply tone (app/pipeline/graph.py) needs to know which channel
        # this is before the pipeline runs, not after.
        channel_repo = ChannelRepository(session)
        channel = await channel_repo.get(tenant_id, channel_id)
        state = PipelineState(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            incoming_text=incoming_text,
            channel_type=channel.type if channel is not None else "telegram",
        )
        async with get_checkpointer() as checkpointer:
            result = await run_pipeline(state, session, checkpointer)

        # Skipped when check_pending_escalation suppressed this run
        # (docs/ROADMAP.md §3.1, state.already_escalated) -- nothing was
        # decided (no LLM calls even ran), so a trace here would write a
        # hollow detected_intent/lead_score/decision row that blanks out a
        # previously-good rail badge for this conversation until the
        # pending escalation is resolved.
        already_escalated = bool(result.get("already_escalated"))
        if not already_escalated:
            await PipelineTraceRepository(session).record_result(
                tenant_id, conversation_id, message_id, result
            )

        # No special-casing for "__interrupt__" here anymore -- an
        # escalation now sets draft_text too (the cover reply,
        # app/pipeline/graph.py's decide_next_step), and the internal note
        # explaining why is already written directly by the graph itself.
        # This block now runs uniformly whether the pipeline paused or not.
        #
        # already_escalated MUST gate this explicitly, not just the trace
        # above -- found live, not anticipated: check_pending_escalation
        # short-circuits to END without decide_next_step/keep_chatting
        # ever running again, but LangGraph's checkpointer merges this
        # run's input with the *previously persisted* channel values for
        # this thread_id rather than replacing them, so `result` still
        # carries the FIRST run's stale draft_text/decision even though
        # nothing was actually decided this time. Without this guard, a
        # second message on an already-escalated conversation would
        # silently re-send the first run's cover reply verbatim as if it
        # were a fresh one.
        draft_text = result.get("draft_text")
        if draft_text and not already_escalated:
            message_repo = MessageRepository(session)
            await message_repo.add(
                Message(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    direction="outbound",
                    audience="customer",
                    text=draft_text,
                )
            )

            conversation_repo = ConversationRepository(session)
            conversation = await conversation_repo.get(tenant_id, conversation_id)
            if conversation is not None and channel is not None and channel.bot_token:
                try:
                    await send_message(
                        channel.bot_token, conversation.external_contact_id, draft_text
                    )
                except Exception:
                    # The reasoning/decision already happened and is worth
                    # keeping either way -- a delivery failure (Telegram
                    # down, bad token, customer blocked the bot) shouldn't
                    # discard the Lead/Message rows already built up in
                    # this transaction. Not re-raising is deliberate for
                    # the same reason -- there's no retry queue for sends
                    # yet (ARCHITECTURE §11 territory) -- but it still gets
                    # logged; silently swallowing it entirely would leave
                    # no record a message was ever dropped.
                    logger.exception(
                        "Failed to deliver Telegram reply for conversation %s",
                        conversation_id,
                    )

        await session.commit()
        await publish_pipeline_events(state, result)


@celery_app.task(name="follow_up_check")
def follow_up_check() -> None:
    """Step 8 of the pipeline (docs/ARCHITECTURE.md §4): periodic scan for
    quiet conversations, run on Celery Beat's schedule
    (app/core/celery_app.py), not triggered per-message like
    process_incoming_message above. Sends at most one follow-up ever per
    conversation (ConversationRepository.list_quiet_unscoped only matches
    ones that haven't been followed up yet) -- if the lead replies after
    that, it's a normal inbound message through the usual channel-ingestion
    path, re-entering the pipeline at step 2 same as any other reply.
    """
    asyncio.run(_follow_up_check())


async def _follow_up_check() -> None:
    cutoff = datetime.now(UTC) - timedelta(hours=settings.follow_up_delay_hours)
    async with async_session() as session:
        conversation_repo = ConversationRepository(session)
        quiet_conversations = await conversation_repo.list_quiet_unscoped(cutoff)

        message_repo = MessageRepository(session)
        channel_repo = ChannelRepository(session)
        for conversation in quiet_conversations:
            sent_channel_type = await _send_follow_up(conversation, message_repo, channel_repo)
            # Committed per-conversation, not once at the end of the batch
            # -- a failure partway through this loop (a bad LLM/network
            # call for one tenant) shouldn't roll back follow-ups already
            # sent for others, and followed_up_at needs to be durable
            # before the next scan runs regardless of what happens later
            # in this loop.
            await session.commit()
            if sent_channel_type is not None:
                await publish_event(
                    conversation.tenant_id,
                    {
                        "type": "message",
                        "channel_type": sent_channel_type,
                        "conversation_id": str(conversation.id),
                    },
                )


async def _send_follow_up(
    conversation: Conversation,
    message_repo: MessageRepository,
    channel_repo: ChannelRepository,
) -> str | None:
    """Returns the channel_type a follow-up was actually written for
    (docs/ROADMAP.md §3.5 -- lets the caller publish a live-update event
    only when a message really was added), or None on any of the early-
    return paths where nothing was written."""
    last_message = await message_repo.get_latest(conversation.tenant_id, conversation.id)
    if last_message is None:
        return None

    try:
        follow_up_text = generate_text(
            "You are a helpful customer support assistant for a small "
            "business. The customer went quiet after your last message to "
            "them -- write a short, natural, friendly check-in, not "
            "pushy, like a real person texting back. Reply in the exact "
            "same language as your last message below (do not translate, "
            "do not switch languages).\n\n"
            f"Your last message to them was: {last_message.text}"
        )
    except Exception:
        logger.exception(
            "Failed to generate a follow-up for conversation %s", conversation.id
        )
        return None

    await message_repo.add(
        Message(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            direction="outbound",
            text=follow_up_text,
        )
    )
    conversation.followed_up_at = datetime.now(UTC)

    channel = await channel_repo.get(conversation.tenant_id, conversation.channel_id)
    if channel is not None and channel.bot_token:
        try:
            await send_message(
                channel.bot_token, conversation.external_contact_id, follow_up_text
            )
        except Exception:
            # Same reasoning as process_incoming_message's own delivery
            # try/except above: the follow-up is still worth recording
            # (and followed_up_at still worth setting, so we don't retry
            # it forever) even if this particular send fails.
            logger.exception(
                "Failed to deliver follow-up for conversation %s", conversation.id
            )

    return channel.type if channel is not None else "telegram"
