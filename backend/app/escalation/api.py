import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.core.db import get_session
from app.escalation.repository import EscalationRepository

router = APIRouter(prefix="/escalations", tags=["escalations"])


class EscalationResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    reason: str
    layer: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("")
async def list_escalations(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[EscalationResponse]:
    escalation_repo = EscalationRepository(session)
    escalations = await escalation_repo.list(current_user.tenant_id)
    return [EscalationResponse.model_validate(escalation) for escalation in escalations]
