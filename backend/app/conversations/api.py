import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.db import get_session

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationResponse(BaseModel):
    id: uuid.UUID
    external_contact_id: str
    status: str
    last_message_text: str | None
    last_message_at: datetime | None
    channel_type: str
    is_test: bool


class MessageResponse(BaseModel):
    id: uuid.UUID
    direction: str
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("")
async def list_conversations(
    channel_type: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ConversationResponse]:
    conversation_repo = ConversationRepository(session)
    rows = await conversation_repo.list_with_last_message(current_user.tenant_id, channel_type)
    return [
        ConversationResponse(
            id=conversation.id,
            external_contact_id=conversation.external_contact_id,
            status=conversation.status,
            last_message_text=message.text if message else None,
            last_message_at=message.created_at if message else None,
            channel_type=channel.type,
            is_test=channel.is_test,
        )
        for conversation, message, channel in rows
    ]


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
