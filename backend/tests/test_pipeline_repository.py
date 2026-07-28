import uuid
from unittest.mock import AsyncMock, MagicMock

from app.pipeline.models import PipelineTrace
from app.pipeline.repository import PipelineTraceRepository


def _fake_session() -> AsyncMock:
    # session.add() is synchronous on a real (Async)Session -- only
    # flush()/commit() are actually async. A bare AsyncMock() would mock
    # .add() as async too, leaving an unawaited-coroutine warning even
    # though TenantScopedRepository.add (app/core/repository.py) never
    # awaits it, by design.
    session = AsyncMock()
    session.add = MagicMock()
    return session


class TestRecordResult:
    async def test_stores_intent_score_and_decision_from_result(self) -> None:
        session = _fake_session()
        repo = PipelineTraceRepository(session)
        tenant_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        message_id = uuid.uuid4()

        await repo.record_result(
            tenant_id,
            conversation_id,
            message_id,
            {
                "detected_intent": "purchase_intent",
                "lead_score": "hot",
                "decision": "escalate_to_human",
                "draft_text": "ignored -- not part of the trace",
            },
        )

        session.add.assert_called_once()
        trace = session.add.call_args.args[0]
        assert isinstance(trace, PipelineTrace)
        assert trace.tenant_id == tenant_id
        assert trace.conversation_id == conversation_id
        assert trace.message_id == message_id
        assert trace.state == {
            "detected_intent": "purchase_intent",
            "lead_score": "hot",
            "decision": "escalate_to_human",
        }

    async def test_missing_fields_default_to_none(self) -> None:
        # The escalated/interrupted branch (pipeline/tasks.py) still calls
        # this with whatever state existed at the pause point -- shouldn't
        # KeyError just because draft_text/etc. were never set.
        session = _fake_session()
        repo = PipelineTraceRepository(session)

        await repo.record_result(
            uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), {"__interrupt__": []}
        )

        trace = session.add.call_args.args[0]
        assert trace.state == {
            "detected_intent": None,
            "lead_score": None,
            "decision": None,
        }


class TestGetLatestByConversationIds:
    async def test_returns_empty_dict_for_no_conversation_ids(self) -> None:
        repo = PipelineTraceRepository(AsyncMock())
        result = await repo.get_latest_by_conversation_ids(uuid.uuid4(), [])
        assert result == {}

    async def test_keys_results_by_conversation_id(self) -> None:
        session = AsyncMock()
        conversation_a = uuid.uuid4()
        conversation_b = uuid.uuid4()
        trace_a = PipelineTrace(
            tenant_id=uuid.uuid4(),
            conversation_id=conversation_a,
            message_id=uuid.uuid4(),
            step="result",
            state={"lead_score": "hot"},
        )
        trace_b = PipelineTrace(
            tenant_id=uuid.uuid4(),
            conversation_id=conversation_b,
            message_id=uuid.uuid4(),
            step="result",
            state={"lead_score": "cold"},
        )
        session.scalars = AsyncMock(return_value=[trace_a, trace_b])
        repo = PipelineTraceRepository(session)

        result = await repo.get_latest_by_conversation_ids(
            uuid.uuid4(), [conversation_a, conversation_b]
        )

        assert result == {conversation_a: trace_a, conversation_b: trace_b}
