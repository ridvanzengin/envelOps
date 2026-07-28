import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.repository import ChannelRepository
from app.channels.telegram_client import TelegramUpdate
from app.conversations.models import Conversation, Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.db import get_session
from app.pipeline.tasks import process_incoming_message

router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("/telegram/{channel_id}/webhook")
async def telegram_webhook(
    channel_id: uuid.UUID,
    update: TelegramUpdate,
    session: AsyncSession = Depends(get_session),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    channel_repo = ChannelRepository(session)
    channel = await channel_repo.get_by_id_unscoped(channel_id)
    if channel is None or channel.type != "telegram":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown channel")

    # No webhook_secret configured is a misconfiguration, not "skip the
    # check" -- an unset secret must never mean an open endpoint.
    if not channel.webhook_secret or x_telegram_bot_api_secret_token != channel.webhook_secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid secret token")

    if update.message is None or update.message.text is None:
        # Not a plain text message (photo, sticker, edited message, ...) --
        # Phase 1 only handles text. Still 200, not an error: Telegram
        # retries non-2xx responses, and there's nothing here to retry.
        return {"status": "ignored"}

    external_contact_id = str(update.message.chat.id)

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
            text=update.message.text,
        )
    )
    # Committed here, in the webhook handler's own session/transaction --
    # the pipeline run happens in a separate session inside the Celery
    # task (ARCHITECTURE §8: kept out of the handler so Telegram gets a
    # fast response), not this one.
    await session.commit()

    process_incoming_message.delay(
        str(channel.tenant_id),
        str(conversation.id),
        str(channel.id),
        str(inbound_message.id),
        update.message.text,
    )

    return {"status": "accepted"}
