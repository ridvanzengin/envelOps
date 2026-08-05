from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.models import Channel
from app.conversations.models import Conversation, Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.events import publish_event


async def ingest_inbound_message(
    channel: Channel, external_contact_id: str, text: str, session: AsyncSession
) -> None:
    """The part of "a DM arrived" that's identical across every channel,
    real or simulated: find-or-create the Conversation, persist the
    inbound Message, commit, publish the live-update event, and hand off
    to the pipeline. Telegram's own handler and the simulated-webhook
    handlers (app/channels/api.py) call this after their own channel-
    specific parsing/auth; the demo DM streamer (app/pipeline/tasks.py's
    stream_demo_dm) calls it directly, in-process, with no webhook/auth
    step at all -- it already knows the Channel row, since it's the one
    that created it.

    process_incoming_message is imported inside this function, not at
    module level, deliberately -- app/pipeline/tasks.py needs to import
    this function too (for stream_demo_dm), and a top-level import here
    would make that a circular import (channels.service -> pipeline.tasks
    -> channels.service)."""
    from app.pipeline.tasks import process_incoming_message
    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get_by_external_contact(
        channel.tenant_id, channel.id, external_contact_id
    )
    if conversation is None:
        conversation = await conversation_repo.add(
            Conversation(
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                external_contact_id=external_contact_id,
            )
        )

    message_repo = MessageRepository(session)
    inbound_message = await message_repo.add(
        Message(
            tenant_id=channel.tenant_id,
            conversation_id=conversation.id,
            direction="inbound",
            text=text,
        )
    )
    # Committed here, in the caller's own session/transaction -- the
    # pipeline run happens in a separate session inside the Celery task
    # (ARCHITECTURE §8: kept out of the handler so the caller gets a fast
    # response), not this one.
    await session.commit()

    # docs/ROADMAP.md §3.5 -- lets an already-open rail update without a
    # manual refetch. Best-effort: a live-update push is a nice-to-have,
    # not a guarantee the inbound message itself already is (it's
    # committed above regardless of whether anyone's listening).
    await publish_event(
        channel.tenant_id,
        {
            "type": "message",
            "channel_type": channel.type,
            "conversation_id": str(conversation.id),
        },
    )

    process_incoming_message.delay(
        str(channel.tenant_id),
        str(conversation.id),
        str(channel.id),
        str(inbound_message.id),
        text,
    )
