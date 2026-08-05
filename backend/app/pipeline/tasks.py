"""Celery task that runs the pipeline for one inbound message
(docs/ARCHITECTURE.md §8's `process_incoming_message`) — the bridge between
channel ingestion (app/channels/api.py) and the pipeline
(app/pipeline/runner.py). Celery tasks are plain sync callables; the
pipeline is async throughout (async DB session, async checkpointer), so
this bridges via `asyncio.run()` once per task invocation — a standard,
accepted pattern for running async code inside a sync Celery worker, not a
workaround.

Uses `app.core.db.worker_async_session` (a NullPool-backed sessionmaker),
not the plain `async_session` the rest of the app uses — see that name's
own docstring in db.py. A pooled connection reused across this file's
separate asyncio.run() calls broke with an asyncpg cross-event-loop error
(found live 2026-08-03, fixed here); imported under the `async_session`
name below so the rest of this file, and the existing test suite's patch
targets, don't need to change.
"""

import asyncio
import logging
import random
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.models import Channel
from app.channels.repository import ChannelRepository
from app.channels.service import ingest_inbound_message
from app.channels.telegram_client import send_message
from app.conversations.models import Conversation, Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.db import worker_async_session as async_session
from app.core.events import publish_event
from app.core.llm import generate_text
from app.escalation.models import Escalation
from app.leads.models import Lead
from app.pipeline.models import PipelineTrace
from app.pipeline.repository import PipelineTraceRepository
from app.pipeline.runner import get_checkpointer, publish_pipeline_events, run_pipeline
from app.pipeline.state import PipelineState
from app.tenants.repository import TenantRepository

logger = logging.getLogger(__name__)

# Demo DM streaming (docs/ROADMAP.md) -- makes the Dashboard/conversation
# rail feel like a genuinely live system to a passive demo visitor, since
# Test Console's own demo-mode path never touches the real rail at all
# (app/test_console/api.py's _send_test_message_demo never commits, never
# publishes an event). Both tasks below check settings.demo_mode_enabled
# FIRST and return immediately otherwise -- the inverse of follow_up_check's
# own demo-mode check further down (that job skips IN demo mode; these two
# only ever run IN demo mode) -- so neither can write to, or delete from, a
# real deployment's database on its own.
_DEMO_STREAM_DAILY_MIN = 10
_DEMO_STREAM_DAILY_MAX = 15
# telegram included deliberately, even though it's this app's one *real*
# channel integration elsewhere -- a Channel row with bot_token=None (what
# get_demo_stream_channel/the lazy-create below always uses) already makes
# _process_incoming_message's own send skip the real Telegram API call, the
# exact same "real pipeline, no real platform contacted" property the other
# 4 types get from being simulated in the first place. Never reuses an
# existing REAL telegram channel -- see get_demo_stream_channel's own
# docstring for why that's checked explicitly, not assumed.
_DEMO_STREAM_CHANNEL_TYPES = ("telegram", "whatsapp", "instagram", "facebook", "email")
_DEMO_RETENTION_DAYS = 7

# Generic customer-support phrasing, deliberately not tied to any one
# tenant's product line -- the real pipeline (knowledge grounding, tool-
# calling) is what makes a reply tenant-specific, this just needs to read
# like a real customer message. No external dataset dependency (unlike
# scripts/seed_calibration_tenant.py's Bitext CSV, which is gitignored and
# not guaranteed present on a deployed demo server) -- a background job
# silently doing nothing because a large file wasn't downloaded would be a
# bad failure mode for a feature whose whole point is "always keeps the
# demo feeling alive." Two constraints on every entry here, both found
# live 2026-08-05: (1) self-contained, no "this"/"it"-style reference to
# an earlier turn -- every streamed DM starts a brand-new conversation
# (see external_contact_id below), so the model has no prior message to
# resolve a dangling pronoun against; (2) vertical-agnostic phrasing --
# this same pool is sent to every demo tenant regardless of business type
# (apparel, electronics, ...), so no sizing/apparel-specific questions
# that would read as nonsensical coming from a gadget-shop customer. Both
# tenants' own knowledge bases still cover sizing for whoever asks it
# organically (Test Console, etc.) -- it's just not in this shared pool.
_DEMO_STREAM_MESSAGES = (
    "Hi, do you ship internationally?",
    "What's your return policy?",
    "Can I change my order after placing it?",
    "How long does delivery usually take?",
    "I haven't received my order yet, can you check on it?",
    "What payment methods do you accept?",
    "Can I get a refund for a damaged item?",
    "Do you offer express shipping?",
    "I'd like to cancel my recent order.",
    "What's your most popular product right now?",
    "Do you have any ongoing discounts or promotions?",
    "Hi there, quick question about my order.",
    "Do your products come with a warranty?",
    "Can I track my package?",
    "Do you accept PayPal?",
    "What's the estimated delivery time for domestic orders?",
)

# Purchase-intent / hot-lead / complaint / escalation-trigger pools, added
# 2026-08-05 (direct instruction) -- the pool above is knowledge_question-
# shaped only, so a demo watcher never saw book_or_checkout, a real
# complaint_or_problem reply, or the safety floor actually firing. Each
# pool below is a set of {}-style templates, not fixed strings -- filled
# in with a random order number/quantity/reference per send
# (_random_order_number/_random_reference) so the same template doesn't
# read as the exact same canned message every time it's picked, same
# realism goal as every entry in _DEMO_STREAM_MESSAGES above.
_PURCHASE_INTENT_TEMPLATES = (
    "I'd like to order {qty} of these -- how do I complete the purchase?",
    "Can I get {qty} units shipped to me? What would the total cost be?",
    "I'm ready to buy this today -- what's the best way to check out?",
    "Can I place an order for {qty} right now?",
)

# Deliberately urgent/ready-to-buy phrasing -- meant to score "hot" via
# score_lead's own judgment (a real LLM classification, not a guaranteed
# outcome any more than any other intent/score call in this pipeline is).
# Both calibration tenants have closing_action="book_or_checkout", so a
# hot purchase-intent lead routes there, not to escalate_to_human -- this
# category exercises the checkout-link handoff, not the safety floor
# (that's _ESCALATION_TRIGGER_MESSAGES below, a deliberately separate
# category).
_HOT_LEAD_TEMPLATES = (
    "I need this delivered by this weekend if at all possible -- order "
    "reference {ref}. Can you make that happen?",
    "I want to place an order right now, please send me the checkout "
    "link immediately.",
    "This is urgent, I need to buy this today -- how fast can you get "
    "it to me? Reference {ref}.",
    "Can I check out immediately? I need this as soon as possible, "
    "reference {ref}.",
)

_COMPLAINT_TEMPLATES = (
    "My order #{order_num} arrived damaged and I'm honestly pretty "
    "frustrated about it.",
    "This is the second issue I've had with order #{order_num} -- not "
    "happy with this experience at all.",
    "I'm really disappointed, order #{order_num} doesn't match what was "
    "described at all.",
    "Order #{order_num} showed up late again, this keeps happening and "
    "it's frustrating.",
)

# Deliberately trips escalation/safety_gate.py's real outcome-guarantee
# pattern (a certainty word -- "guarantee"/"promise"/"100% guaranteed" --
# plus an efficacy/risk word -- "work"/"fix"/"safe"/"risk" -- in the same
# message, see that module's own docstring). Written to be plausible for
# either business vertical (cold-weather jacket performance, power-bank
# flight safety) rather than the module's original health-adjacent
# framing, which wouldn't make sense coming from an apparel/electronics
# customer -- the pattern itself doesn't require health language, only
# these two word categories together in the same message.
_ESCALATION_TRIGGER_MESSAGES = (
    "Can you guarantee this will definitely work in extreme cold weather?",
    "Can you guarantee this is completely safe to bring on a flight?",
    "Do you promise this will fix the issue I'm having, 100% guaranteed?",
    "Is there any risk this could be dangerous if I use it every day?",
)

# Weights, not a uniform 1-in-5 -- knowledge questions dominate real DM
# traffic; escalation-trigger messages should stay rare, same as real
# safety-floor hits are rare in practice, not routine.
_MESSAGE_CATEGORY_WEIGHTS = {
    "knowledge": 0.45,
    "purchase_intent": 0.20,
    "hot_lead": 0.15,
    "complaint": 0.15,
    "escalation_trigger": 0.05,
}


def _random_order_number() -> int:
    return random.randint(10000, 99999)


def _random_reference() -> str:
    return f"REQ-{random.randint(1000, 9999)}"


def _generate_demo_message() -> str:
    category = random.choices(
        list(_MESSAGE_CATEGORY_WEIGHTS), weights=list(_MESSAGE_CATEGORY_WEIGHTS.values()), k=1
    )[0]
    if category == "knowledge":
        return random.choice(_DEMO_STREAM_MESSAGES)
    if category == "purchase_intent":
        return random.choice(_PURCHASE_INTENT_TEMPLATES).format(qty=random.randint(1, 5))
    if category == "hot_lead":
        return random.choice(_HOT_LEAD_TEMPLATES).format(ref=_random_reference())
    if category == "complaint":
        return random.choice(_COMPLAINT_TEMPLATES).format(order_num=_random_order_number())
    return random.choice(_ESCALATION_TRIGGER_MESSAGES)


@celery_app.task(name="process_incoming_message")
def process_incoming_message(
    tenant_id: str,
    conversation_id: str,
    channel_id: str,
    message_id: str,
    incoming_text: str,
) -> None:
    asyncio.run(
        _process_incoming_message(
            uuid.UUID(tenant_id),
            uuid.UUID(conversation_id),
            uuid.UUID(channel_id),
            uuid.UUID(message_id),
            incoming_text,
        )
    )


async def _process_incoming_message(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    channel_id: uuid.UUID,
    message_id: uuid.UUID,
    incoming_text: str,
) -> None:
    async with async_session() as session:
        # Fetched up front (not just later for bot_token/send below) so its
        # type can drive channel_type -- keep_chatting/book_or_checkout's
        # reply tone (app/pipeline/graph.py) needs to know which channel
        # this is before the pipeline runs, not after.
        channel_repo = ChannelRepository(session)
        channel = await channel_repo.get(tenant_id, channel_id)
        state = PipelineState(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            incoming_text=incoming_text,
            channel_type=channel.type if channel is not None else "telegram",
        )
        async with get_checkpointer() as checkpointer:
            result = await run_pipeline(state, session, checkpointer)

        # Skipped when check_pending_escalation suppressed this run
        # (docs/ROADMAP.md §3.1, state.already_escalated) -- nothing was
        # decided (no LLM calls even ran), so a trace here would write a
        # hollow detected_intent/lead_score/decision row that blanks out a
        # previously-good rail badge for this conversation until the
        # pending escalation is resolved.
        already_escalated = bool(result.get("already_escalated"))
        if not already_escalated:
            await PipelineTraceRepository(session).record_result(
                tenant_id, conversation_id, message_id, result
            )

        # No special-casing for "__interrupt__" here anymore -- an
        # escalation now sets draft_text too (the cover reply,
        # app/pipeline/graph.py's decide_next_step), and the internal note
        # explaining why is already written directly by the graph itself.
        # This block now runs uniformly whether the pipeline paused or not.
        #
        # already_escalated MUST gate this explicitly, not just the trace
        # above -- found live, not anticipated: check_pending_escalation
        # short-circuits to END without decide_next_step/keep_chatting
        # ever running again, but LangGraph's checkpointer merges this
        # run's input with the *previously persisted* channel values for
        # this thread_id rather than replacing them, so `result` still
        # carries the FIRST run's stale draft_text/decision even though
        # nothing was actually decided this time. Without this guard, a
        # second message on an already-escalated conversation would
        # silently re-send the first run's cover reply verbatim as if it
        # were a fresh one.
        # ai_enabled gates only this block -- the pipeline run above (and
        # its trace/escalation/lead side effects) always happens
        # regardless, so the rail/dashboard stay populated even while a
        # channel's AI is switched off (docs/ROADMAP.md, Channels page
        # 2026-08-03). Only the customer-facing reply is suppressed.
        draft_text = result.get("draft_text")
        ai_enabled = channel is not None and channel.ai_enabled
        if draft_text and not already_escalated and ai_enabled:
            message_repo = MessageRepository(session)
            await message_repo.add(
                Message(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    direction="outbound",
                    audience="customer",
                    text=draft_text,
                )
            )

            conversation_repo = ConversationRepository(session)
            conversation = await conversation_repo.get(tenant_id, conversation_id)
            if conversation is not None and channel is not None and channel.bot_token:
                try:
                    await send_message(
                        channel.bot_token, conversation.external_contact_id, draft_text
                    )
                except Exception:
                    # The reasoning/decision already happened and is worth
                    # keeping either way -- a delivery failure (Telegram
                    # down, bad token, customer blocked the bot) shouldn't
                    # discard the Lead/Message rows already built up in
                    # this transaction. Not re-raising is deliberate for
                    # the same reason -- there's no retry queue for sends
                    # yet (ARCHITECTURE §11 territory) -- but it still gets
                    # logged; silently swallowing it entirely would leave
                    # no record a message was ever dropped.
                    logger.exception(
                        "Failed to deliver Telegram reply for conversation %s",
                        conversation_id,
                    )

        await session.commit()
        await publish_pipeline_events(state, result)


@celery_app.task(name="follow_up_check")
def follow_up_check() -> None:
    """Step 8 of the pipeline (docs/ARCHITECTURE.md §4): periodic scan for
    quiet conversations, run on Celery Beat's schedule
    (app/core/celery_app.py), not triggered per-message like
    process_incoming_message above. Sends at most one follow-up ever per
    conversation (ConversationRepository.list_quiet_unscoped only matches
    ones that haven't been followed up yet) -- if the lead replies after
    that, it's a normal inbound message through the usual channel-ingestion
    path, re-entering the pipeline at step 2 same as any other reply.
    """
    if settings.demo_mode_enabled:
        # No background job writes to a public demo's database on its own
        # -- every other write path in demo mode is blocked at the API
        # layer (app/core/demo_mode.py), but this one isn't reachable
        # through the API at all, so it needs its own check.
        logger.info("Skipping follow_up_check: demo_mode_enabled is on")
        return
    asyncio.run(_follow_up_check())


async def _follow_up_check() -> None:
    cutoff = datetime.now(UTC) - timedelta(hours=settings.follow_up_delay_hours)
    async with async_session() as session:
        conversation_repo = ConversationRepository(session)
        quiet_conversations = await conversation_repo.list_quiet_unscoped(cutoff)

        message_repo = MessageRepository(session)
        channel_repo = ChannelRepository(session)
        for conversation in quiet_conversations:
            sent_channel_type = await _send_follow_up(conversation, message_repo, channel_repo)
            # Committed per-conversation, not once at the end of the batch
            # -- a failure partway through this loop (a bad LLM/network
            # call for one tenant) shouldn't roll back follow-ups already
            # sent for others, and followed_up_at needs to be durable
            # before the next scan runs regardless of what happens later
            # in this loop.
            await session.commit()
            if sent_channel_type is not None:
                await publish_event(
                    conversation.tenant_id,
                    {
                        "type": "message",
                        "channel_type": sent_channel_type,
                        "conversation_id": str(conversation.id),
                    },
                )


async def _send_follow_up(
    conversation: Conversation,
    message_repo: MessageRepository,
    channel_repo: ChannelRepository,
) -> str | None:
    """Returns the channel_type a follow-up was actually written for
    (docs/ROADMAP.md §3.5 -- lets the caller publish a live-update event
    only when a message really was added), or None on any of the early-
    return paths where nothing was written."""
    channel = await channel_repo.get(conversation.tenant_id, conversation.channel_id)
    if channel is None or not channel.ai_enabled:
        # A follow-up nudge is itself an AI-generated auto-reply, so a
        # channel with AI switched off (Channels page, 2026-08-03) stays
        # fully silent here too, not just non-responsive to new inbound
        # messages. Checked before the LLM call below, not after, so
        # disabled channels don't spend a Gemini call on text nobody will
        # see.
        return None

    last_message = await message_repo.get_latest(conversation.tenant_id, conversation.id)
    if last_message is None:
        return None

    try:
        follow_up_text = generate_text(
            "You are a helpful customer support assistant for a small "
            "business. The customer went quiet after your last message to "
            "them -- write a short, natural, friendly check-in, not "
            "pushy, like a real person texting back. Reply in the exact "
            "same language as your last message below (do not translate, "
            "do not switch languages).\n\n"
            f"Your last message to them was: {last_message.text}"
        )
    except Exception:
        logger.exception(
            "Failed to generate a follow-up for conversation %s", conversation.id
        )
        return None

    await message_repo.add(
        Message(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            direction="outbound",
            text=follow_up_text,
        )
    )
    conversation.followed_up_at = datetime.now(UTC)

    if channel.bot_token:
        try:
            await send_message(
                channel.bot_token, conversation.external_contact_id, follow_up_text
            )
        except Exception:
            # Same reasoning as process_incoming_message's own delivery
            # try/except above: the follow-up is still worth recording
            # (and followed_up_at still worth setting, so we don't retry
            # it forever) even if this particular send fails.
            logger.exception(
                "Failed to deliver follow-up for conversation %s", conversation.id
            )

    return channel.type


@celery_app.task(name="stream_demo_dm")
def stream_demo_dm() -> None:
    """Fires at most one simulated inbound DM per tick, paced against a
    10-15/day target picked once per calendar day -- see this module's own
    _DEMO_STREAM_* constants and demo-mode-gating comment above. Runs on
    Celery Beat's schedule (app/core/celery_app.py), same shape as
    follow_up_check below, just with the demo-mode check inverted."""
    if not settings.demo_mode_enabled:
        logger.info("Skipping stream_demo_dm: demo_mode_enabled is off")
        return
    asyncio.run(_stream_demo_dm())


def _demo_stream_daily_target(today: date) -> int:
    # Deterministic per calendar day, not re-randomized every tick (which
    # would make the "sent >= target" check below keep moving under it)
    # but still varies day to day for a less mechanical feel.
    return random.Random(today.isoformat()).randint(
        _DEMO_STREAM_DAILY_MIN, _DEMO_STREAM_DAILY_MAX
    )


async def _count_inbound_since(
    session: AsyncSession, tenant_ids: list[uuid.UUID], since: datetime
) -> int:
    stmt = (
        select(func.count(Message.id))
        .select_from(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.direction == "inbound",
            Message.created_at >= since,
            Conversation.tenant_id.in_(tenant_ids),
        )
    )
    return int(await session.scalar(stmt) or 0)


def _should_send_now(sent_today: int, target: int, elapsed_fraction: float) -> bool:
    """True when today's actual send count is behind where a smooth
    10-15/day pace would put it by this point in the day -- self-corrects
    if a tick is missed (worker restart, etc.) since it's driven by an
    actual count, not an in-memory counter, and spreads sends across the
    day instead of bursting them all right after midnight. Split out as
    its own pure function so it's directly unit-testable without needing
    to mock datetime.now()."""
    if sent_today >= target:
        return False
    return sent_today < target * elapsed_fraction


async def _stream_demo_dm() -> None:
    async with async_session() as session:
        tenant_rows = await TenantRepository(session).list_with_owner_unscoped()
        tenant_ids = [tenant.id for tenant, _user in tenant_rows]
        if not tenant_ids:
            return

        now = datetime.now(UTC)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        target = _demo_stream_daily_target(now.date())
        sent_today = await _count_inbound_since(session, tenant_ids, start_of_day)
        elapsed_fraction = (now - start_of_day).total_seconds() / 86400
        if not _should_send_now(sent_today, target, elapsed_fraction):
            return

        tenant_id = random.choice(tenant_ids)
        channel_type = random.choice(_DEMO_STREAM_CHANNEL_TYPES)
        text = _generate_demo_message()

        channel_repo = ChannelRepository(session)
        channel = await channel_repo.get_demo_stream_channel(tenant_id, channel_type)
        if channel is None:
            channel = await channel_repo.add(
                Channel(
                    tenant_id=tenant_id,
                    type=channel_type,
                    external_account_id=f"demo-stream-{channel_type}",
                    is_test=False,
                    bot_token=None,
                    webhook_secret=secrets.token_urlsafe(32),
                )
            )

        external_contact_id = f"demo-{uuid.uuid4().hex[:10]}"
        await ingest_inbound_message(channel, external_contact_id, text, session)


@celery_app.task(name="purge_stale_demo_data")
def purge_stale_demo_data() -> None:
    """Rolling _DEMO_RETENTION_DAYS-day retention for demo DM streaming's
    own data -- deletes conversations (and everything under them:
    messages, leads, escalations, pipeline traces) whose most recent
    message is older than the cutoff, keeping the whole demo history
    uniformly "recent" rather than mixing a long-fixed calibration-seeded
    set with an ever-growing rolling window. Same demo-mode gate as
    stream_demo_dm above -- doubly important here, since this is a real
    delete, not just a write."""
    if not settings.demo_mode_enabled:
        logger.info("Skipping purge_stale_demo_data: demo_mode_enabled is off")
        return
    asyncio.run(_purge_stale_demo_data())


async def _purge_stale_demo_data() -> int:
    cutoff = datetime.now(UTC) - timedelta(days=_DEMO_RETENTION_DAYS)
    async with async_session() as session:
        latest_message = (
            select(Message.conversation_id, func.max(Message.created_at).label("latest"))
            .group_by(Message.conversation_id)
            .subquery()
        )
        stale_ids_stmt = select(latest_message.c.conversation_id).where(
            latest_message.c.latest < cutoff
        )
        stale_ids = list((await session.scalars(stale_ids_stmt)).all())
        if not stale_ids:
            return 0

        # Deletion order respects each model's own ForeignKey (none
        # declare ondelete=CASCADE): PipelineTrace references both
        # conversation_id and message_id, so it goes first; Message can
        # reference escalation_id, so it must be deleted before Escalation;
        # Lead and Conversation have nothing referencing them from here.
        # Does NOT clean up LangGraph's own checkpoint tables (thread_id =
        # str(conversation_id), no Postgres FK to our tables at all, see
        # CLAUDE.md's checkpointer gotchas) -- orphaned rows there are
        # harmless (no constraint violation risk) and rare in practice
        # (only conversations that actually hit escalate_to_human's real
        # interrupt() get one), so left as a known gap rather than adding
        # a second, differently-keyed delete path for this first pass.
        await session.execute(
            delete(PipelineTrace).where(PipelineTrace.conversation_id.in_(stale_ids))
        )
        await session.execute(delete(Message).where(Message.conversation_id.in_(stale_ids)))
        await session.execute(
            delete(Escalation).where(Escalation.conversation_id.in_(stale_ids))
        )
        await session.execute(delete(Lead).where(Lead.conversation_id.in_(stale_ids)))
        await session.execute(delete(Conversation).where(Conversation.id.in_(stale_ids)))
        await session.commit()

        logger.info(
            "Purged %d stale demo conversation(s) older than %d day(s)",
            len(stale_ids),
            _DEMO_RETENTION_DAYS,
        )
        return len(stale_ids)
