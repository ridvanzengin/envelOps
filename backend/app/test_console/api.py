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
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.channels.models import Channel
from app.channels.repository import ChannelRepository
from app.conversations.models import Conversation, Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.config import settings
from app.core.db import get_session
from app.core.events import publish_event
from app.pipeline.models import PipelineTrace
from app.pipeline.repository import PipelineTraceRepository
from app.pipeline.runner import get_checkpointer, publish_pipeline_events, run_pipeline
from app.pipeline.state import PipelineState

router = APIRouter(prefix="/test", tags=["test"])


class MessageDiagnostics(BaseModel):
    """The per-message pipeline reasoning (docs/ROADMAP.md §3.4) -- lets the
    tenant owner see *why* the pipeline replied the way it did for each
    inbound message, not just the final reply. Only ever set for inbound
    messages (a pipeline run's own `PipelineState`, ARCHITECTURE §4, doesn't
    exist for an outbound one)."""

    detected_intent: str | None
    lead_score: str | None
    decision: str | None


class TestMessageResponse(BaseModel):
    id: uuid.UUID
    direction: str
    text: str
    created_at: datetime
    audience: str
    escalation_id: uuid.UUID | None
    diagnostics: MessageDiagnostics | None = None


def _to_response(
    message: Message, trace_by_message_id: dict[uuid.UUID, PipelineTrace]
) -> TestMessageResponse:
    trace = trace_by_message_id.get(message.id)
    diagnostics = (
        MessageDiagnostics(
            detected_intent=trace.state.get("detected_intent"),
            lead_score=trace.state.get("lead_score"),
            decision=trace.state.get("decision"),
        )
        if trace is not None
        else None
    )
    return TestMessageResponse(
        id=message.id,
        direction=message.direction,
        text=message.text,
        created_at=message.created_at,
        audience=message.audience,
        escalation_id=message.escalation_id,
        diagnostics=diagnostics,
    )


async def _list_messages_with_diagnostics(
    session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[TestMessageResponse]:
    messages = await MessageRepository(session).list_by_conversation(
        tenant_id, conversation_id
    )
    traces = await PipelineTraceRepository(session).list_by_conversation(
        tenant_id, conversation_id
    )
    trace_by_message_id = {trace.message_id: trace for trace in traces}
    return [_to_response(message, trace_by_message_id) for message in messages]


class TestConversationResponse(BaseModel):
    conversation_id: uuid.UUID | None
    messages: list[TestMessageResponse]


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
    messages: list[TestMessageResponse]
    escalated: bool
    escalation_reason: str | None


# Demo mode's counterpart to everything below -- runs the exact same real
# pipeline (real Gemini calls, real knowledge search) but never creates a
# Channel/Conversation row and never writes a Message/PipelineTrace row,
# so a public read-only demo leaves nothing in Postgres from Test Console
# use, matching every other write path's demo_mode_enabled gate
# (app/core/demo_mode.py) even though this one can't just 403 -- the
# point of Test Console is that it still runs.
#
# Two process-local (not per-request) stores, deliberately not Postgres/
# Redis: a demo's whole point is that this is throwaway, so losing it on
# restart is a feature, not a gap.
#   - _demo_checkpointer: one shared in-memory LangGraph checkpointer.
#     Using MemorySaver here instead of get_checkpointer()'s
#     AsyncPostgresSaver also sidesteps the checkpointer/session
#     cross-driver hang CLAUDE.md documents (psycopg vs asyncpg) --
#     there's no second real DB connection involved at all.
#   - _demo_conversation_messages: per (tenant, channel_type, session)
#     accumulated message list, keyed the same way a real Conversation
#     row would be looked up (ConversationRepository.get_by_external_contact),
#     just never persisted.
_demo_checkpointer = MemorySaver()
_demo_conversation_messages: dict[tuple[uuid.UUID, str, str], list[TestMessageResponse]] = {}


def _demo_key(
    tenant_id: uuid.UUID, channel_type: str, external_contact_id: str
) -> tuple[uuid.UUID, str, str]:
    return (tenant_id, channel_type, external_contact_id)


def _demo_thread_id(
    tenant_id: uuid.UUID, channel_type: str, external_contact_id: str
) -> uuid.UUID:
    # Deterministic, not random -- the same (tenant, channel_type, session)
    # must map to the same LangGraph thread_id on every call, or a second
    # message in the same Test Console session would start a fresh thread
    # instead of continuing the conversation (escalation pause/resume,
    # multi-turn context) the way a real persisted Conversation.id would.
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{channel_type}:{external_contact_id}")


@router.get("/conversations")
async def get_test_conversation(
    channel_type: str,
    external_contact_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TestConversationResponse:
    if settings.demo_mode_enabled:
        key = _demo_key(current_user.tenant_id, channel_type, external_contact_id)
        history = _demo_conversation_messages.get(key, [])
        if not history:
            return TestConversationResponse(conversation_id=None, messages=[])
        return TestConversationResponse(
            conversation_id=_demo_thread_id(
                current_user.tenant_id, channel_type, external_contact_id
            ),
            messages=list(history),
        )

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

    messages = await _list_messages_with_diagnostics(
        session, current_user.tenant_id, conversation.id
    )
    return TestConversationResponse(conversation_id=conversation.id, messages=messages)


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

    if settings.demo_mode_enabled:
        return await _send_test_message_demo(
            body, stripped, external_contact_id, current_user, session
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
    inbound_message = await message_repo.add(
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
    await publish_event(
        current_user.tenant_id,
        {
            "type": "message",
            "channel_type": body.channel_type,
            "conversation_id": str(conversation.id),
        },
    )

    state = PipelineState(
        tenant_id=current_user.tenant_id,
        conversation_id=conversation.id,
        incoming_text=stripped,
        channel_type=body.channel_type,
    )
    async with get_checkpointer() as checkpointer:
        result = await run_pipeline(state, session, checkpointer)

    # escalated/escalation_reason kept for the response's own top-level
    # fields (testConsole.escalatedNotice) -- unrelated to whether
    # draft_text gets written below, which now happens uniformly for both
    # branches (docs/ROADMAP.md §3.1: an escalation sets draft_text to a
    # cover reply too, no special-casing needed here anymore).
    escalated = "__interrupt__" in result
    escalation_reason = None
    if escalated:
        interrupt = result["__interrupt__"][0]
        escalation_reason = interrupt.value.get("escalation_reason")

    # already_escalated MUST gate draft_text explicitly -- found live, not
    # anticipated: check_pending_escalation short-circuits to END without
    # decide_next_step/keep_chatting ever running again, but LangGraph's
    # checkpointer merges this run's input with the *previously persisted*
    # channel values for this thread_id rather than replacing them, so
    # `result` still carries the FIRST run's stale draft_text/decision
    # even though nothing was actually decided this time. Without this
    # guard, a second message on an already-escalated conversation would
    # silently re-send the first run's cover reply verbatim.
    already_escalated = bool(result.get("already_escalated"))
    draft_text = result.get("draft_text")
    if draft_text and not already_escalated:
        await message_repo.add(
            Message(
                tenant_id=current_user.tenant_id,
                conversation_id=conversation.id,
                direction="outbound",
                audience="customer",
                text=draft_text,
            )
        )

    # Skipped when check_pending_escalation suppressed this run -- nothing
    # was decided, so a trace here would blank out a previously-good
    # diagnostics badge.
    if not already_escalated:
        # One trace row per inbound message, keyed by message_id --
        # surfaced back in both this response and GET /test/conversations
        # (_list_messages_with_diagnostics) so the per-message reasoning
        # (docs/ROADMAP.md §3.4) survives a platform switch/page reload,
        # not just the message just sent.
        await PipelineTraceRepository(session).record_result(
            current_user.tenant_id, conversation.id, inbound_message.id, result
        )
    await session.commit()
    await publish_pipeline_events(state, result)

    messages = await _list_messages_with_diagnostics(
        session, current_user.tenant_id, conversation.id
    )
    return SendTestMessageResponse(
        conversation_id=conversation.id,
        messages=messages,
        escalated=escalated,
        escalation_reason=escalation_reason,
    )


async def _send_test_message_demo(
    body: SendTestMessageRequest,
    stripped: str,
    external_contact_id: str,
    current_user: CurrentUser,
    session: AsyncSession,
) -> SendTestMessageResponse:
    """Demo-mode counterpart to send_test_message above -- see the module
    docstring near _demo_checkpointer for the persistence story. One real
    difference from the persisted flow: graph.py's own nodes
    (log_lead_and_notify, escalate_to_human) still stage real Lead/
    Escalation/internal-note rows on `session` as they always do -- this
    function just never calls session.commit() after run_pipeline, so
    those staged rows are discarded when the request's session closes
    rather than ever reaching Postgres, the same "nothing written" outcome
    every other demo-mode-gated endpoint gets via an outright 403. One
    known gap from that: the internal-note bubble a real escalation writes
    (app/pipeline/graph.py's _write_internal_note) lives only in that
    discarded session state, not in this function's own history list --
    the escalation is still fully visible via this response's own
    escalated/escalation_reason fields and the inbound message's
    diagnostics badge, just not as a second chat bubble.
    """
    key = _demo_key(current_user.tenant_id, body.channel_type, external_contact_id)
    conversation_id = _demo_thread_id(
        current_user.tenant_id, body.channel_type, external_contact_id
    )
    history = _demo_conversation_messages.setdefault(key, [])

    # Same "commit before invoking a checkpointed run" hygiene CLAUDE.md
    # documents for the real flow above -- nothing is actually pending
    # here (demo mode never session.add()s a Channel/Conversation/Message
    # itself), but this still clears any open transaction/autoflush state
    # before the graph runs, the same defensive habit for the same reason.
    await session.commit()

    state = PipelineState(
        tenant_id=current_user.tenant_id,
        conversation_id=conversation_id,
        incoming_text=stripped,
        channel_type=body.channel_type,
    )
    result = await run_pipeline(state, session, _demo_checkpointer)

    escalated = "__interrupt__" in result
    escalation_reason = None
    if escalated:
        interrupt = result["__interrupt__"][0]
        escalation_reason = interrupt.value.get("escalation_reason")

    already_escalated = bool(result.get("already_escalated"))
    diagnostics = (
        MessageDiagnostics(
            detected_intent=result.get("detected_intent"),
            lead_score=result.get("lead_score"),
            decision=result.get("decision"),
        )
        if not already_escalated
        else None
    )
    history.append(
        TestMessageResponse(
            id=uuid.uuid4(),
            direction="inbound",
            text=stripped,
            created_at=datetime.now(UTC),
            audience="customer",
            escalation_id=None,
            diagnostics=diagnostics,
        )
    )

    draft_text = result.get("draft_text")
    if draft_text and not already_escalated:
        history.append(
            TestMessageResponse(
                id=uuid.uuid4(),
                direction="outbound",
                text=draft_text,
                created_at=datetime.now(UTC),
                audience="customer",
                escalation_id=None,
            )
        )

    return SendTestMessageResponse(
        conversation_id=conversation_id,
        messages=list(history),
        escalated=escalated,
        escalation_reason=escalation_reason,
    )
