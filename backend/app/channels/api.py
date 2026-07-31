import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.models import Channel
from app.channels.repository import ChannelRepository
from app.channels.simulated_client import (
    EmailWebhookPayload,
    MetaMessagingEvent,
    WhatsAppMessage,
)
from app.channels.telegram_client import TelegramUpdate
from app.conversations.models import Conversation, Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.db import get_session
from app.core.events import publish_event
from app.pipeline.tasks import process_incoming_message

router = APIRouter(prefix="/channels", tags=["channels"])

# All 4 simulated channels (Instagram/WhatsApp/Facebook/Email) check one
# uniform, EnvelOps-owned secret header -- not each real platform's own
# signing scheme (Meta's HMAC-based X-Hub-Signature-256, etc.). Building
# real per-platform signature verification for fake integrations would be
# exactly the over-engineering this simulation is meant to avoid; the
# fail-closed posture (missing/wrong secret -> 403) is preserved.
_SIMULATED_SECRET_HEADER = "X-EnvelOps-Simulated-Webhook-Secret"


async def _ingest_inbound_message(
    channel: Channel, external_contact_id: str, text: str, session: AsyncSession
) -> None:
    """The part of "a DM arrived" that's identical across every channel,
    real or simulated: find-or-create the Conversation, persist the
    inbound Message, commit, publish the live-update event, and hand off
    to the pipeline. Telegram's own handler calls this too, after its
    Telegram-specific parsing/auth."""
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
    # Committed here, in the webhook handler's own session/transaction --
    # the pipeline run happens in a separate session inside the Celery
    # task (ARCHITECTURE §8: kept out of the handler so the caller gets a
    # fast response), not this one.
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

    await _ingest_inbound_message(
        channel, str(update.message.chat.id), update.message.text, session
    )
    return {"status": "accepted"}


async def _simulated_webhook(
    channel_id: uuid.UUID,
    expected_type: str,
    external_contact_id: str,
    text: str | None,
    session: AsyncSession,
    secret_header: str | None,
) -> dict[str, str]:
    channel_repo = ChannelRepository(session)
    channel = await channel_repo.get_by_id_unscoped(channel_id)
    if channel is None or channel.type != expected_type:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown channel")
    if not channel.webhook_secret or secret_header != channel.webhook_secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid secret token")
    if not text:
        return {"status": "ignored"}
    await _ingest_inbound_message(channel, external_contact_id, text, session)
    return {"status": "accepted"}


@router.post("/instagram/{channel_id}/webhook")
async def instagram_webhook(
    channel_id: uuid.UUID,
    payload: MetaMessagingEvent,
    session: AsyncSession = Depends(get_session),
    secret: str | None = Header(default=None, alias=_SIMULATED_SECRET_HEADER),
) -> dict[str, str]:
    text = payload.message.text if payload.message else None
    return await _simulated_webhook(
        channel_id, "instagram", payload.sender.id, text, session, secret
    )


@router.post("/facebook/{channel_id}/webhook")
async def facebook_webhook(
    channel_id: uuid.UUID,
    payload: MetaMessagingEvent,
    session: AsyncSession = Depends(get_session),
    secret: str | None = Header(default=None, alias=_SIMULATED_SECRET_HEADER),
) -> dict[str, str]:
    text = payload.message.text if payload.message else None
    return await _simulated_webhook(
        channel_id, "facebook", payload.sender.id, text, session, secret
    )


@router.post("/whatsapp/{channel_id}/webhook")
async def whatsapp_webhook(
    channel_id: uuid.UUID,
    payload: WhatsAppMessage,
    session: AsyncSession = Depends(get_session),
    secret: str | None = Header(default=None, alias=_SIMULATED_SECRET_HEADER),
) -> dict[str, str]:
    text = payload.text.body if payload.text else None
    return await _simulated_webhook(
        channel_id, "whatsapp", payload.from_, text, session, secret
    )


@router.post("/email/{channel_id}/webhook")
async def email_webhook(
    channel_id: uuid.UUID,
    payload: EmailWebhookPayload,
    session: AsyncSession = Depends(get_session),
    secret: str | None = Header(default=None, alias=_SIMULATED_SECRET_HEADER),
) -> dict[str, str]:
    return await _simulated_webhook(
        channel_id, "email", payload.from_address, payload.text, session, secret
    )
