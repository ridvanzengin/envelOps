import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
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
from app.core.demo_mode import block_in_demo_mode
from app.core.events import publish_event
from app.pipeline.tasks import process_incoming_message

router = APIRouter(prefix="/channels", tags=["channels"])


class ChannelResponse(BaseModel):
    id: uuid.UUID
    type: str
    status: str
    ai_enabled: bool

    model_config = {"from_attributes": True}


class UpdateChannelAIRequest(BaseModel):
    ai_enabled: bool


@router.get("/connected")
async def list_channels(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ChannelResponse]:
    """The Channels page's real channel list -- Test Console channels
    excluded (ChannelRepository.list_non_test), since those are a
    separate, always-manual mechanism, not something this page manages.
    Deliberately not a bare `GET /channels` -- `/channels` is also a real
    frontend page route (Channels.tsx), and a bare collection-root GET
    here would need the same page-route/proxy collision workaround
    `/knowledge` already hit once (frontend/vite.config.ts's own
    comment); `/knowledge/sources` sidesteps it the same way this does."""
    channel_repo = ChannelRepository(session)
    channels = await channel_repo.list_non_test(current_user.tenant_id)
    return [ChannelResponse.model_validate(channel) for channel in channels]


@router.patch("/{channel_id}")
async def update_channel_ai(
    channel_id: uuid.UUID,
    body: UpdateChannelAIRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(block_in_demo_mode),
) -> ChannelResponse:
    """The Channels page's AI on/off switch -- direct field mutation +
    commit, the same shape resolve_escalation (app/escalation/api.py)
    already uses for a single-field status change, not a new pattern.
    Takes effect at the two places that actually turn a pipeline result
    into a customer-facing message (app/pipeline/tasks.py's
    _process_incoming_message and _send_follow_up) -- the pipeline itself
    keeps running either way, only the send is gated."""
    channel_repo = ChannelRepository(session)
    channel = await channel_repo.get(current_user.tenant_id, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")

    channel.ai_enabled = body.ai_enabled
    await session.commit()
    return ChannelResponse.model_validate(channel)

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
    _: None = Depends(block_in_demo_mode),
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
    _: None = Depends(block_in_demo_mode),
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
    _: None = Depends(block_in_demo_mode),
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
    _: None = Depends(block_in_demo_mode),
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
    _: None = Depends(block_in_demo_mode),
) -> dict[str, str]:
    return await _simulated_webhook(
        channel_id, "email", payload.from_address, payload.text, session, secret
    )
