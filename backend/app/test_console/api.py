"""Test Console (frontend TestConsole.tsx) -- lets the tenant owner send a
message through the real pipeline against any channel type, without a real
integration for that channel existing yet. Built to validate that reply
tone actually differs per channel (app/pipeline/graph.py's
_CHANNEL_TONE_GUIDANCE) before sinking time into a real Instagram/WhatsApp/
etc. integration.

No models.py/repository.py here -- reuses Channel/Conversation/Message as-is,
same as every other module in this codebase (none of them use a separate
service.py either; logic lives directly in the route handlers).

Runs the pipeline synchronously (calls run_pipeline directly, not via the
Celery task real channels use) -- a human is watching and waiting for the
reply, and there's no webhook needing a fast response to hand off from.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.channels.models import Channel
from app.channels.repository import ChannelRepository
from app.conversations.api import MessageResponse
from app.conversations.models import Conversation, Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.db import get_session
from app.pipeline.runner import get_checkpointer, run_pipeline
from app.pipeline.state import PipelineState

router = APIRouter(prefix="/test", tags=["test"])


class TestConversationResponse(BaseModel):
    conversation_id: uuid.UUID | None
    messages: list[MessageResponse]


class SendTestMessageRequest(BaseModel):
    channel_type: str
    # Frontend-generated per test "session" (TestConsole.tsx's New Session
    # button/fresh mount) -- there's no real external contact for a test
    # channel, so this is what makes repeated messages within the same
    # session continue the same thread (reusing
    # ConversationRepository.get_by_external_contact exactly like the
    # Telegram webhook handler, app/channels/api.py, does for real
    # contacts), while a new session gets its own independent Conversation
    # row, trackable on its own in ChannelRail/ConversationPanel.
    external_contact_id: str
    text: str


class SendTestMessageResponse(BaseModel):
    conversation_id: uuid.UUID
    messages: list[MessageResponse]
    escalated: bool
    escalation_reason: str | None


@router.get("/conversations")
async def get_test_conversation(
    channel_type: str,
    external_contact_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TestConversationResponse:
    channel_repo = ChannelRepository(session)
    channel = await channel_repo.get_test_channel(current_user.tenant_id, channel_type)
    conversation = (
        await ConversationRepository(session).get_by_external_contact(
            current_user.tenant_id, channel.id, external_contact_id
        )
        if channel is not None
        else None
    )
    if conversation is None:
        return TestConversationResponse(conversation_id=None, messages=[])

    message_repo = MessageRepository(session)
    messages = await message_repo.list_by_conversation(current_user.tenant_id, conversation.id)
    return TestConversationResponse(
        conversation_id=conversation.id,
        messages=[MessageResponse.model_validate(message) for message in messages],
    )


@router.post("/conversations/messages")
async def send_test_message(
    body: SendTestMessageRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SendTestMessageResponse:
    stripped = body.text.strip()
    if not stripped:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "text must not be blank")
    external_contact_id = body.external_contact_id.strip()
    if not external_contact_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "external_contact_id must not be blank"
        )

    channel_repo = ChannelRepository(session)
    channel = await channel_repo.get_test_channel(current_user.tenant_id, body.channel_type)
    if channel is None:
        channel = await channel_repo.add(
            Channel(
                tenant_id=current_user.tenant_id,
                type=body.channel_type,
                external_account_id="test",
                is_test=True,
            )
        )

    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get_by_external_contact(
        current_user.tenant_id, channel.id, external_contact_id
    )
    if conversation is None:
        conversation = await conversation_repo.add(
            Conversation(
                tenant_id=current_user.tenant_id,
                channel_id=channel.id,
                external_contact_id=external_contact_id,
            )
        )

    message_repo = MessageRepository(session)
    await message_repo.add(
        Message(
            tenant_id=current_user.tenant_id,
            conversation_id=conversation.id,
            direction="inbound",
            text=stripped,
        )
    )
    # Commit before run_pipeline -- the checkpointer writes over a separate
    # psycopg connection from this session's asyncpg one, and an open
    # transaction here has hung a checkpointed run indefinitely before
    # (CLAUDE.md's checkpointer gotcha).
    await session.commit()

    state = PipelineState(
        tenant_id=current_user.tenant_id,
        conversation_id=conversation.id,
        incoming_text=stripped,
        channel_type=body.channel_type,
    )
    async with get_checkpointer() as checkpointer:
        result = await run_pipeline(state, session, checkpointer)

    escalated = "__interrupt__" in result
    escalation_reason = None
    if escalated:
        interrupt = result["__interrupt__"][0]
        escalation_reason = interrupt.value.get("escalation_reason")
    else:
        draft_text = result.get("draft_text")
        if draft_text:
            await message_repo.add(
                Message(
                    tenant_id=current_user.tenant_id,
                    conversation_id=conversation.id,
                    direction="outbound",
                    text=draft_text,
                )
            )
    await session.commit()

    messages = await message_repo.list_by_conversation(current_user.tenant_id, conversation.id)
    return SendTestMessageResponse(
        conversation_id=conversation.id,
        messages=[MessageResponse.model_validate(message) for message in messages],
        escalated=escalated,
        escalation_reason=escalation_reason,
    )
