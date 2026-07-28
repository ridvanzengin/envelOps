import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.channels.models import Channel
from app.channels.repository import ChannelRepository
from app.conversations.repository import ConversationRepository
from app.core.db import get_session
from app.escalation.models import Escalation, TenantTriggerPhrase
from app.escalation.repository import EscalationRepository, TenantTriggerPhraseRepository
from app.pipeline.runner import get_checkpointer, resume_pipeline

router = APIRouter(prefix="/escalations", tags=["escalations"])


class EscalationResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    reason: str
    layer: str
    status: str
    created_at: datetime
    channel_type: str
    is_test: bool

    model_config = {"from_attributes": True}


class TriggerPhraseResponse(BaseModel):
    id: uuid.UUID
    phrase: str

    model_config = {"from_attributes": True}


class CreateTriggerPhraseRequest(BaseModel):
    phrase: str


def _to_response(escalation: Escalation, channel: Channel) -> EscalationResponse:
    """channel_type/is_test live on Channel, not Escalation -- model_validate's
    from_attributes only ever reads one source object, so this merges the two
    by hand instead."""
    return EscalationResponse(
        id=escalation.id,
        conversation_id=escalation.conversation_id,
        reason=escalation.reason,
        layer=escalation.layer,
        status=escalation.status,
        created_at=escalation.created_at,
        channel_type=channel.type,
        is_test=channel.is_test,
    )


@router.get("")
async def list_escalations(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[EscalationResponse]:
    escalation_repo = EscalationRepository(session)
    rows = await escalation_repo.list_with_channel_info(current_user.tenant_id)
    return [_to_response(escalation, channel) for escalation, channel in rows]


@router.post("/{escalation_id}/resolve")
async def resolve_escalation(
    escalation_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EscalationResponse:
    """No request body: resolving here only clears the queue and unpauses
    the checkpointed pipeline thread (docs/ARCHITECTURE.md §5) so the
    conversation can continue on the next inbound message -- it does not
    submit a reply. Phase 1 has no draft-and-approve mechanism (§5), and
    escalate_to_human's interrupt() doesn't consume a resume value for
    anything, so there's nothing for a reply-text field to do yet; the
    human handles the actual customer-facing reply outside the tool.
    """
    escalation_repo = EscalationRepository(session)
    escalation = await escalation_repo.get(current_user.tenant_id, escalation_id)
    if escalation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "escalation not found")
    if escalation.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "escalation is not pending")

    escalation.status = "resolved"
    # Commit before resume_pipeline -- the checkpointer writes over a
    # separate psycopg connection from this session's asyncpg one, and an
    # open transaction here has hung a checkpointed run indefinitely
    # before (CLAUDE.md's checkpointer gotcha).
    await session.commit()

    async with get_checkpointer() as checkpointer:
        # Must be non-None -- Command(resume=None) hits an UnboundLocalError
        # inside langgraph's own loop internals (resume_is_map only gets
        # assigned when `resume is not None`, then gets read unconditionally
        # a few lines later). Found by running this against a real
        # AsyncPostgresSaver, not the mocked/InMemorySaver unit tests, which
        # only ever passed dict resume values. The value itself is never
        # read by escalate_to_human -- content doesn't matter, truthiness does.
        resume_value = {"resolved_by": str(current_user.user_id)}
        await resume_pipeline(escalation.conversation_id, resume_value, session, checkpointer)
    # log_lead_and_notify runs as part of the resume above and flushes a
    # Lead row on this same session -- commit it, same as every other
    # caller of run_pipeline/resume_pipeline owns its own commit.
    await session.commit()

    conversation = await ConversationRepository(session).get(
        current_user.tenant_id, escalation.conversation_id
    )
    channel = (
        await ChannelRepository(session).get(current_user.tenant_id, conversation.channel_id)
        if conversation is not None
        else None
    )
    # Neither should be possible in practice (an escalation's conversation/
    # channel disappearing mid-resolve) -- 500s rather than silently
    # returning a response with made-up channel info.
    if conversation is None or channel is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "escalation's conversation or channel is missing",
        )

    return _to_response(escalation, channel)


@router.get("/trigger-phrases")
async def list_trigger_phrases(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TriggerPhraseResponse]:
    """Only the tenant's own additions -- system defaults (docs/
    ARCHITECTURE.md §5) are compiled regex in safety_gate.py, not DB rows,
    so there's nothing here to list for them; the frontend shows those as
    static, locked copy instead."""
    phrase_repo = TenantTriggerPhraseRepository(session)
    phrases = await phrase_repo.list(current_user.tenant_id)
    return [TriggerPhraseResponse.model_validate(phrase) for phrase in phrases]


@router.post("/trigger-phrases")
async def add_trigger_phrase(
    body: CreateTriggerPhraseRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TriggerPhraseResponse:
    stripped = body.phrase.strip()
    if not stripped:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "phrase must not be blank")

    phrase_repo = TenantTriggerPhraseRepository(session)
    phrase = await phrase_repo.add(
        TenantTriggerPhrase(tenant_id=current_user.tenant_id, phrase=stripped)
    )
    await session.commit()
    return TriggerPhraseResponse.model_validate(phrase)


@router.delete("/trigger-phrases/{phrase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trigger_phrase(
    phrase_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Deletable as of 2026-07-29 -- a deliberate reversal of the original
    additive-only design (REQUIREMENTS.md §6 has the full reasoning, both
    the original and why it changed): the trade-off of a tenant being able
    to remove a phrase it added (and so weaken its own floor) was accepted
    over leaving a mistaken/typo'd phrase permanently stuck. System
    defaults are unaffected either way -- they're compiled regex in
    safety_gate.py, not rows in this table, so there is still no code path
    that touches them."""
    phrase_repo = TenantTriggerPhraseRepository(session)
    phrase = await phrase_repo.get(current_user.tenant_id, phrase_id)
    if phrase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "trigger phrase not found")
    await phrase_repo.delete(phrase)
    await session.commit()
