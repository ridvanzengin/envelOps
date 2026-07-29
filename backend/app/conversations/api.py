import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.db import get_session
from app.pipeline.repository import PipelineTraceRepository

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationResponse(BaseModel):
    id: uuid.UUID
    external_contact_id: str
    status: str
    last_message_text: str | None
    last_message_at: datetime | None
    channel_type: str
    is_test: bool
    # Latest pipeline_traces row for this conversation, if any -- rail/
    # list-row badges (docs/ROADMAP.md §3.3). Refreshed whenever this list
    # is refetched (on opening a channel), not pushed live yet -- that's
    # ROADMAP §3.5's SSE work, not this one.
    detected_intent: str | None
    lead_score: str | None


class MessageResponse(BaseModel):
    id: uuid.UUID
    direction: str
    text: str
    created_at: datetime
    # docs/ROADMAP.md §3.1 -- "internal" rows are escalation notes, visible
    # only to the business owner, never sent to the customer.
    audience: str
    escalation_id: uuid.UUID | None

    model_config = {"from_attributes": True}


@router.get("")
async def list_conversations(
    channel_type: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ConversationResponse]:
    conversation_repo = ConversationRepository(session)
    rows = await conversation_repo.list_with_last_message(current_user.tenant_id, channel_type)
    trace_by_conversation_id = await PipelineTraceRepository(
        session
    ).get_latest_by_conversation_ids(
        current_user.tenant_id, [conversation.id for conversation, _, _ in rows]
    )

    responses = []
    for conversation, message, channel in rows:
        trace = trace_by_conversation_id.get(conversation.id)
        responses.append(
            ConversationResponse(
                id=conversation.id,
                external_contact_id=conversation.external_contact_id,
                status=conversation.status,
                last_message_text=message.text if message else None,
                last_message_at=message.created_at if message else None,
                channel_type=channel.type,
                is_test=channel.is_test,
                detected_intent=trace.state.get("detected_intent") if trace else None,
                lead_score=trace.state.get("lead_score") if trace else None,
            )
        )
    return responses


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    conversation_repo = ConversationRepository(session)
    conversation = await conversation_repo.get(current_user.tenant_id, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    message_repo = MessageRepository(session)
    messages = await message_repo.list_by_conversation(
        current_user.tenant_id, conversation_id
    )
    return [MessageResponse.model_validate(message) for message in messages]
