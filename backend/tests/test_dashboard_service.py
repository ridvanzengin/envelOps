import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.dashboard.service import (
    ChannelStat,
    _avg_response_minutes,
    _channel_stats,
    _daily_counts,
    _hourly_counts,
    _intent_breakdown,
)


def _message(**overrides: object) -> MagicMock:
    message = MagicMock()
    message.conversation_id = overrides.pop("conversation_id", uuid.uuid4())
    message.direction = "inbound"
    message.created_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(message, key, value)
    return message


def _channel(channel_type: str) -> MagicMock:
    channel = MagicMock()
    channel.type = channel_type
    return channel


def _escalation(status: str) -> MagicMock:
    escalation = MagicMock()
    escalation.status = status
    return escalation


def _trace(detected_intent: str | None) -> MagicMock:
    trace = MagicMock()
    trace.state = {"detected_intent": detected_intent}
    return trace


class TestAvgResponseMinutes:
    def test_returns_none_with_no_messages(self) -> None:
        assert _avg_response_minutes([]) is None

    def test_returns_none_when_no_inbound_was_ever_answered(self) -> None:
        messages = [_message(direction="inbound")]
        assert _avg_response_minutes(messages) is None

    def test_pairs_inbound_with_the_next_outbound_in_the_same_conversation(self) -> None:
        conversation_id = uuid.uuid4()
        t0 = datetime.now(UTC)
        messages = [
            _message(conversation_id=conversation_id, direction="inbound", created_at=t0),
            _message(
                conversation_id=conversation_id,
                direction="outbound",
                created_at=t0 + timedelta(minutes=10),
            ),
        ]
        assert _avg_response_minutes(messages) == 10.0

    def test_does_not_cross_conversation_boundaries(self) -> None:
        t0 = datetime.now(UTC)
        conversation_a = uuid.uuid4()
        conversation_b = uuid.uuid4()
        messages = [
            _message(conversation_id=conversation_a, direction="inbound", created_at=t0),
            # A different conversation's outbound message must not pair
            # with conversation_a's still-unanswered inbound one.
            _message(
                conversation_id=conversation_b,
                direction="outbound",
                created_at=t0 + timedelta(minutes=5),
            ),
        ]
        assert _avg_response_minutes(messages) is None

    def test_only_pairs_with_the_most_recent_unanswered_inbound(self) -> None:
        conversation_id = uuid.uuid4()
        t0 = datetime.now(UTC)
        messages = [
            _message(conversation_id=conversation_id, direction="inbound", created_at=t0),
            _message(
                conversation_id=conversation_id,
                direction="inbound",
                created_at=t0 + timedelta(minutes=2),
            ),
            _message(
                conversation_id=conversation_id,
                direction="outbound",
                created_at=t0 + timedelta(minutes=6),
            ),
        ]
        # Pairs with the second inbound message (2->6 = 4 minutes), not the
        # first (0->6 = 6 minutes) -- a customer's follow-up message before
        # any reply resets what "the question being answered" means.
        assert _avg_response_minutes(messages) == 4.0


class TestDailyCounts:
    def test_zero_fills_days_with_no_rows(self) -> None:
        end = datetime.now(UTC)
        points = _daily_counts([], end, 3)
        assert [p.count for p in points] == [0, 0, 0]
        assert len(points) == 3

    def test_buckets_by_day(self) -> None:
        end = datetime.now(UTC)
        dates = [
            (end - timedelta(days=1)).date(),
            (end - timedelta(days=1)).date(),
            end.date(),
        ]
        points = _daily_counts(dates, end, 2)
        assert [p.count for p in points] == [2, 1]

    def test_todays_bucket_is_always_included(self) -> None:
        """The real bug this guards: an earlier version anchored the
        bucket range on `start` and looped forward, which excluded
        *today* whenever `end`'s time-of-day was later than `start`'s
        (always true) -- a tenant's entire day of activity would vanish
        from the trend while still counting toward the stat tile's
        total. Found live against real seeded data (docs/ROADMAP.md's
        dashboard build)."""
        end = datetime.now(UTC)
        points = _daily_counts([end.date()], end, 30)
        assert points[-1].date == end.date().isoformat()
        assert points[-1].count == 1


class TestHourlyCounts:
    def test_zero_fills_hours_with_no_rows(self) -> None:
        end = datetime.now(UTC)
        points = _hourly_counts([], end, 3)
        assert [p.count for p in points] == [0, 0, 0]
        assert len(points) == 3

    def test_buckets_by_hour(self) -> None:
        end = datetime.now(UTC)
        timestamps = [
            end - timedelta(hours=1),
            end - timedelta(hours=1, minutes=30),
            end,
        ]
        points = _hourly_counts(timestamps, end, 2)
        # Both the on-the-hour and half-past timestamp fall in the same
        # "1 hour ago" bucket -- minute-level precision must not fragment
        # a single hour into multiple buckets.
        assert [p.count for p in points] == [2, 1]

    def test_current_hour_is_always_included(self) -> None:
        """Same real bug _daily_counts's own equivalent test guards
        against, one level finer: anchored on `end`'s current hour, not
        `start`, so the most recent hour's activity can't silently drop
        off the end of the window."""
        end = datetime.now(UTC)
        points = _hourly_counts([end], end, 24)
        assert points[-1].count == 1

    def test_minutes_within_the_hour_dont_fragment_the_bucket(self) -> None:
        end = datetime.now(UTC).replace(minute=45, second=30, microsecond=0)
        points = _hourly_counts([end], end, 1)
        assert points[0].count == 1
        assert points[0].date == end.replace(minute=0, second=0, microsecond=0).isoformat()


class TestIntentBreakdown:
    def test_empty_when_no_traces_have_an_intent(self) -> None:
        assert _intent_breakdown([_trace(None)]) == []

    def test_computes_counts_and_percentages_in_fixed_order(self) -> None:
        traces = [
            _trace("purchase_intent"),
            _trace("purchase_intent"),
            _trace("small_talk"),
            _trace(None),  # excluded from the total, not counted as "other"
        ]
        items = _intent_breakdown(traces)
        assert [(i.intent, i.count, i.percentage) for i in items] == [
            ("purchase_intent", 2, round(2 / 3 * 100, 1)),
            ("small_talk", 1, round(1 / 3 * 100, 1)),
        ]


class TestChannelStats:
    def test_resolution_rate_is_none_with_zero_escalations(self) -> None:
        telegram = _channel("telegram")
        conversations = [(MagicMock(), telegram)]
        stats = _channel_stats(conversations, [])
        assert stats == [
            ChannelStat(channel_type="telegram", conversations=1, resolution_rate=None)
        ]

    def test_resolution_rate_only_counts_that_channels_escalations(self) -> None:
        telegram = _channel("telegram")
        instagram = _channel("instagram")
        conversations = [(MagicMock(), telegram), (MagicMock(), instagram)]
        escalations = [
            (_escalation("resolved"), telegram),
            (_escalation("pending"), telegram),
            (_escalation("resolved"), instagram),
        ]
        stats = {s.channel_type: s for s in _channel_stats(conversations, escalations)}
        assert stats["telegram"].resolution_rate == 0.5
        assert stats["instagram"].resolution_rate == 1.0

    def test_sorted_by_conversation_count_descending(self) -> None:
        telegram = _channel("telegram")
        instagram = _channel("instagram")
        conversations = [
            (MagicMock(), instagram),
            (MagicMock(), telegram),
            (MagicMock(), telegram),
        ]
        stats = _channel_stats(conversations, [])
        assert [s.channel_type for s in stats] == ["telegram", "instagram"]
