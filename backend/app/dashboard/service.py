import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.models import Channel
from app.conversations.models import Conversation, Message
from app.conversations.repository import ConversationRepository, MessageRepository
from app.escalation.models import Escalation
from app.escalation.repository import EscalationRepository
from app.leads.repository import LeadRepository
from app.pipeline.models import PipelineTrace
from app.pipeline.repository import PipelineTraceRepository

# Matches understand_intent's fixed taxonomy (app/pipeline/graph.py
# _INTENT_LABELS) -- fixed display order for the breakdown, not
# alphabetical or count-sorted, so the order doesn't jump around between
# loads (docs/ROADMAP.md dashboard build, dataviz skill's categorical
# "fixed order, never cycled" rule).
_INTENT_ORDER = (
    "purchase_intent",
    "complaint_or_problem",
    "knowledge_question",
    "small_talk",
    "other",
)


class TrendPoint(BaseModel):
    date: str
    count: int


class IntentBreakdownItem(BaseModel):
    intent: str
    count: int
    percentage: float


class ChannelStat(BaseModel):
    channel_type: str
    conversations: int
    # None (not 0) when the channel had zero escalations in range -- a
    # 0/0 rate is undefined, not "0% resolved"; the frontend renders this
    # as "-" rather than a misleading number.
    resolution_rate: float | None


class DashboardSummary(BaseModel):
    range_days: int
    total_conversations: int
    total_conversations_prev: int
    hot_leads: int
    hot_leads_prev: int
    # Traces classified complaint_or_problem in range -- same "count of
    # what happened," not a resolution-state reading, as hot_leads above
    # (unlike escalated below, a complaint has no separate resolved/
    # pending status of its own to filter on).
    complaints: int
    complaints_prev: int
    # Currently-*unresolved* escalations created in range, not a running
    # total of everything that was ever escalated -- resolving one drops
    # this number, since it's meant to answer "how many need attention
    # right now," not "how many happened." Direct feedback: the total-
    # count version didn't move when an escalation was resolved, which
    # read as a bug for a tile with an alert-triangle icon sitting next
    # to hot-leads/response-time (both now-facing, actionable numbers).
    # The "Top Channels" resolution-rate column is the other reading
    # (resolved / total created) -- that one still needs the full set,
    # computed separately in _channel_stats below.
    escalated: int
    escalated_prev: int
    # None when no inbound message in range was ever followed by an
    # outbound one -- no data point exists to average, not zero minutes.
    avg_response_minutes: float | None
    conversations_trend: list[TrendPoint]
    hot_leads_trend: list[TrendPoint]
    complaints_trend: list[TrendPoint]
    escalated_trend: list[TrendPoint]
    intent_breakdown: list[IntentBreakdownItem]
    channels: list[ChannelStat]


def _avg_response_minutes(messages: list[Message]) -> float | None:
    """Average outbound-after-inbound latency, per conversation -- the
    closest thing to a "response time" this data model supports (no
    dedicated timestamp for it; docs/ROADMAP.md's dashboard build found
    this gap directly). Tracks the most recent not-yet-answered inbound
    message per conversation; the next outbound message closes it out.
    Messages outside the requested range that opened a still-pending gap
    are invisible to this function by construction (the caller only ever
    passes messages already scoped to the range), so a conversation whose
    inbound message landed just before the window starts won't be paired
    -- an accepted undercount at the edges, not a bug to chase.
    """
    pending_inbound_at: dict[uuid.UUID, datetime] = {}
    deltas_minutes: list[float] = []
    for message in sorted(messages, key=lambda m: m.created_at):
        if message.direction == "inbound":
            pending_inbound_at[message.conversation_id] = message.created_at
        elif message.direction == "outbound":
            inbound_at = pending_inbound_at.pop(message.conversation_id, None)
            if inbound_at is not None:
                deltas_minutes.append((message.created_at - inbound_at).total_seconds() / 60)
    if not deltas_minutes:
        return None
    return sum(deltas_minutes) / len(deltas_minutes)


def _daily_counts(dates: list[date], end: datetime, days: int) -> list[TrendPoint]:
    """`days` calendar-day buckets ending at `end`'s date (today), zero-
    filled -- a plain GROUP BY only returns days that actually have a
    row, and a trend chart with silently-missing days reads as a data
    gap, not "zero that day". Shared by every stat tile's sparkline
    (conversations/hot leads/complaints/escalations) -- each caller just
    picks which rows' dates to bucket first.

    Anchored on `end` (today), not `start` -- an earlier version anchored
    on `start` and looped `range(days)` forward, which covers
    [start_date, start_date + days) and silently excludes *today*
    whenever `now`'s time-of-day is later than `start`'s (always true,
    since they're exactly `days` apart): a tenant's entire day's activity
    would vanish from the chart while still counting toward the stat
    tile's total. Found live -- a real dashboard showing 42 conversations
    in the stat tile above a completely flat trend line underneath it,
    docs/ROADMAP.md's dashboard build. The DB query range [start, now)
    and this calendar-day range are inherently not identical (a rolling
    window vs. calendar buckets) -- the oldest bucket may undercount a
    few hours of activity right at the boundary; accepted, since the
    alternative (today silently missing) is the far worse failure mode.
    """
    counts: Counter[date] = Counter(dates)
    end_date = end.date()
    return [
        TrendPoint(
            date=(end_date - timedelta(days=days - 1 - i)).isoformat(),
            count=counts.get(end_date - timedelta(days=days - 1 - i), 0),
        )
        for i in range(days)
    ]


def _intent_breakdown(traces: list[PipelineTrace]) -> list[IntentBreakdownItem]:
    intents = [
        intent
        for trace in traces
        if (intent := trace.state.get("detected_intent")) is not None
    ]
    total = len(intents)
    if total == 0:
        return []
    counts = Counter(intents)
    return [
        IntentBreakdownItem(
            intent=intent,
            count=counts[intent],
            percentage=round(counts[intent] / total * 100, 1),
        )
        for intent in _INTENT_ORDER
        if intent in counts
    ]


def _channel_stats(
    conversations_with_channel: list[tuple[Conversation, Channel]],
    escalations_with_channel: list[tuple[Escalation, Channel]],
) -> list[ChannelStat]:
    conversation_counts: Counter[str] = Counter(
        channel.type for _, channel in conversations_with_channel
    )
    escalation_totals: Counter[str] = Counter(
        channel.type for _, channel in escalations_with_channel
    )
    escalation_resolved: Counter[str] = Counter(
        channel.type
        for escalation, channel in escalations_with_channel
        if escalation.status == "resolved"
    )
    return [
        ChannelStat(
            channel_type=channel_type,
            conversations=count,
            resolution_rate=(
                escalation_resolved.get(channel_type, 0) / escalation_totals[channel_type]
                if escalation_totals.get(channel_type)
                else None
            ),
        )
        for channel_type, count in conversation_counts.most_common()
    ]


async def compute_summary(
    session: AsyncSession, tenant_id: uuid.UUID, days: int
) -> DashboardSummary:
    """Everything the dashboard page needs in one round trip -- filters
    (the days selector) scope every stat/chart/table together, so the
    numbers always agree with each other (dataviz skill's interaction
    rules). Deliberately does most of its counting/grouping in Python over
    plain tenant+date-range row fetches rather than dense aggregate SQL --
    this project's real data volumes (a handful of calibration tenants,
    dozens of messages each) don't need more than that, matching this
    codebase's existing "a plain approach is fine at this scale" calls
    elsewhere (CLAUDE.md on fine-tuning)."""
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    conversation_repo = ConversationRepository(session)
    message_repo = MessageRepository(session)
    lead_repo = LeadRepository(session)
    escalation_repo = EscalationRepository(session)
    trace_repo = PipelineTraceRepository(session)

    conversations = await conversation_repo.list_in_range_with_channel(tenant_id, start, now)
    prev_conversations = await conversation_repo.list_in_range_with_channel(
        tenant_id, prev_start, start
    )
    # No "prev" fetch -- avg_response_minutes has no previous-period
    # comparison (StatTile renders it as a bare value, no delta).
    messages = await message_repo.list_in_range(tenant_id, start, now)
    leads = await lead_repo.list_in_range(tenant_id, start, now)
    prev_leads = await lead_repo.list_in_range(tenant_id, prev_start, start)
    escalations = await escalation_repo.list_with_channel_info(tenant_id, start, now)
    prev_escalations = await escalation_repo.list_with_channel_info(
        tenant_id, prev_start, start
    )
    traces = await trace_repo.list_in_range(tenant_id, start, now)
    prev_traces = await trace_repo.list_in_range(tenant_id, prev_start, start)

    hot_leads = [lead for lead in leads if lead.score == "hot"]
    # Same "count of what happened in range" reading as hot_leads above --
    # unlike escalated below, a complaint has no separate resolved/pending
    # status of its own to filter to "still needs attention."
    complaints = [
        t for t in traces if t.state.get("detected_intent") == "complaint_or_problem"
    ]
    prev_complaints = [
        t for t in prev_traces if t.state.get("detected_intent") == "complaint_or_problem"
    ]
    # Filtered to current status, not "as it stood when created" (this
    # data model has no resolved_at to reconstruct a past snapshot from,
    # CLAUDE.md) -- so this reads as "of what was escalated in range,
    # how much is still unresolved right now," which is what makes the
    # number actually drop when a human resolves one.
    unresolved_escalations = [e for e, _ in escalations if e.status == "pending"]
    prev_unresolved_escalations = [e for e, _ in prev_escalations if e.status == "pending"]

    return DashboardSummary(
        range_days=days,
        total_conversations=len(conversations),
        total_conversations_prev=len(prev_conversations),
        hot_leads=len(hot_leads),
        hot_leads_prev=sum(1 for lead in prev_leads if lead.score == "hot"),
        complaints=len(complaints),
        complaints_prev=len(prev_complaints),
        escalated=len(unresolved_escalations),
        escalated_prev=len(prev_unresolved_escalations),
        avg_response_minutes=_avg_response_minutes(messages),
        conversations_trend=_daily_counts(
            [c.created_at.date() for c, _ in conversations], now, days
        ),
        hot_leads_trend=_daily_counts(
            [lead.created_at.date() for lead in hot_leads], now, days
        ),
        complaints_trend=_daily_counts([t.created_at.date() for t in complaints], now, days),
        escalated_trend=_daily_counts(
            [e.created_at.date() for e in unresolved_escalations], now, days
        ),
        intent_breakdown=_intent_breakdown(traces),
        channels=_channel_stats(conversations, escalations),
    )
