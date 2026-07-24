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

from app.channels.repository import ChannelRepository
from app.channels.telegram_client import send_message
from app.conversations.models import Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.celery_app import celery_app
from app.core.db import async_session
from app.pipeline.runner import get_checkpointer, run_pipeline
from app.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


@celery_app.task(name="process_incoming_message")
def process_incoming_message(
    tenant_id: str, conversation_id: str, channel_id: str, incoming_text: str
) -> None:
    asyncio.run(
        _process_incoming_message(
            uuid.UUID(tenant_id),
            uuid.UUID(conversation_id),
            uuid.UUID(channel_id),
            incoming_text,
        )
    )


async def _process_incoming_message(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    channel_id: uuid.UUID,
    incoming_text: str,
) -> None:
    async with async_session() as session:
        state = PipelineState(
            tenant_id=tenant_id, conversation_id=conversation_id, incoming_text=incoming_text
        )
        async with get_checkpointer() as checkpointer:
            result = await run_pipeline(state, session, checkpointer)

        if "__interrupt__" in result:
            # decide_next_step already logged the Escalation before this
            # pause happened (see its own comment on why). Nothing else to
            # do: no auto-reply on an escalated conversation, that's the
            # entire point of the safety floor.
            await session.commit()
            return

        draft_text = result.get("draft_text")
        if draft_text:
            message_repo = MessageRepository(session)
            await message_repo.add(
                Message(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    direction="outbound",
                    text=draft_text,
                )
            )

            conversation_repo = ConversationRepository(session)
            conversation = await conversation_repo.get(tenant_id, conversation_id)
            channel_repo = ChannelRepository(session)
            channel = await channel_repo.get(tenant_id, channel_id)
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
