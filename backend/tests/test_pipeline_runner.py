import uuid
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Interrupt

from app.core.llm import ToolCallRequest
from app.pipeline.runner import publish_pipeline_events, resume_pipeline, run_pipeline
from app.pipeline.state import PipelineState

# LangGraph's in-memory checkpointer runs the identical interrupt/resume
# mechanics as the real Postgres-backed one (docs/ARCHITECTURE.md §5) --
# only the storage differs, so this is a legitimate way to test the pause/
# resume cycle fast and without needing a real database, not a stand-in
# that skips the thing actually being tested. The real backend was smoke-
# tested separately against Postgres (see PR description).


def _make_state(text: str) -> PipelineState:
    return PipelineState(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        incoming_text=text,
        channel_type="telegram",
    )


class TestRunPipelinePauses:
    async def test_pauses_at_escalate_to_human_on_safety_trigger(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my allergy?")
        with (
            patch("app.pipeline.graph.generate_text", return_value="other"),
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
        ):
            mock_tenant_repo_cls.return_value.get = AsyncMock(
                return_value=type("Tenant", (), {"behavior_config": {}})()
            )
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_message_repo_cls.return_value.list_by_conversation = AsyncMock(
                return_value=[]
            )
            result = await run_pipeline(state, AsyncMock(), InMemorySaver())

        assert "__interrupt__" in result
        assert result["decision"] == "escalate_to_human"
        interrupt = result["__interrupt__"][0]
        assert interrupt.value["conversation_id"] == str(state.conversation_id)
        assert interrupt.value["escalation_reason"] is not None
        # decide_next_step logs the escalation immediately, before the pause
        # -- a human needs to see it to know to resume it in the first place.
        mock_escalation_repo_cls.return_value.add.assert_called_once()

    async def test_book_or_checkout_with_no_link_does_not_pause(self) -> None:
        # Real distinction worth pinning down: book_or_checkout downgrading
        # to decision=escalate_to_human on a missing closing_link is NOT
        # the same as a real safety-floor pause -- routing already happened
        # at decide_next_step, so this proceeds straight to
        # log_lead_and_notify (which logs a real Escalation row) instead of
        # interrupt()-pausing like the actual escalate_to_human node does.
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        fake_tenant = type(
            "Tenant",
            (),
            {
                "closing_action": "book_or_checkout",
                "closing_link": None,
                "behavior_config": {},
            },
        )()
        with (
            patch(
                "app.pipeline.graph.generate_text",
                side_effect=["purchase_intent", "hot", "Someone will follow up soon!"],
            ),
            patch("app.pipeline.graph.embed_text", return_value=[0.1]),
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_knowledge_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
        ):
            mock_knowledge_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_message_repo_cls.return_value.list_by_conversation = AsyncMock(
                return_value=[]
            )
            result = await run_pipeline(state, AsyncMock(), InMemorySaver())

        assert "__interrupt__" not in result
        assert result["decision"] == "escalate_to_human"
        mock_escalation_repo_cls.return_value.add.assert_called_once()

    async def test_does_not_pause_on_an_ordinary_message(self) -> None:
        state = _make_state("What flavors do you have?")
        with (
            patch("app.pipeline.graph.generate_text", return_value="cold"),
            patch("app.pipeline.graph.embed_text", return_value=[0.1]),
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_knowledge_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_tenant_repo_cls.return_value.get = AsyncMock(
                return_value=type("Tenant", (), {"behavior_config": {}})()
            )
            mock_knowledge_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            result = await run_pipeline(state, AsyncMock(), InMemorySaver())

        assert "__interrupt__" not in result
        assert result["decision"] == "keep_chatting"

    async def test_second_message_on_an_already_escalated_conversation_is_a_no_op(
        self,
    ) -> None:
        # docs/ROADMAP.md §3.1 -- the concrete gap this whole guard exists
        # for: empirically verified separately that calling run_pipeline
        # again on an already-interrupted thread_id doesn't resume or
        # no-op on its own, it silently starts a fresh run. Without
        # check_pending_escalation, THIS message would reach
        # understand_intent/decide_next_step and could produce a second
        # reply or a second Escalation row. With it, nothing past
        # check_pending_escalation ever runs -- not even one LLM call.
        state = _make_state("Any update on my order?")
        fake_pending = type("Escalation", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.generate_text") as mock_generate_text,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=fake_pending
            )
            result = await run_pipeline(state, AsyncMock(), InMemorySaver())

        assert "__interrupt__" not in result
        assert result["already_escalated"] is True
        assert result.get("decision") is None
        assert result.get("draft_text") is None
        mock_generate_text.assert_not_called()

    async def test_second_run_on_a_real_paused_thread_does_not_leak_stale_draft_text(
        self,
    ) -> None:
        # Regression test for a real bug found live, not caught by the
        # test above: that one seeds get_pending_by_conversation directly,
        # with no real prior checkpoint on this thread_id. The actual bug
        # only showed up with a REAL first run's checkpoint already
        # sitting on the same thread_id -- LangGraph's checkpointer merges
        # a second invocation's input with the *previously persisted*
        # channel values rather than replacing them, so the first run's
        # draft_text/decision were still present in the second run's
        # result even though check_pending_escalation correctly routed it
        # straight to END. check_pending_escalation must reset those
        # fields itself when skipping, not just set already_escalated.
        checkpointer = InMemorySaver()
        first_state = _make_state("Can you guarantee this will definitely cure my allergy?")
        fake_escalation = type("Escalation", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.generate_text", return_value="Cover reply text"),
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
        ):
            mock_tenant_repo_cls.return_value.get = AsyncMock(
                return_value=type("Tenant", (), {"behavior_config": {}})()
            )
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_message_repo_cls.return_value.list_by_conversation = AsyncMock(
                return_value=[]
            )

            # First run: nothing pending yet -- this run is the one that
            # creates the escalation and pauses.
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            first = await run_pipeline(first_state, AsyncMock(), checkpointer)
            assert "__interrupt__" in first
            assert first["draft_text"] == "Cover reply text"

            # Second run, same thread_id (conversation_id) -- the
            # escalation from the first run is now pending.
            second_state = _make_state("Anyone there?")
            second_state.conversation_id = first_state.conversation_id
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=fake_escalation
            )
            second = await run_pipeline(second_state, AsyncMock(), checkpointer)

        assert second["already_escalated"] is True
        assert second.get("draft_text") is None
        assert second.get("decision") is None


class TestRunPipelineToolCalling:
    """The only place call_tools's actual insertion into the compiled
    graph (build_pipeline_graph's decide_next_step -> call_tools ->
    keep_chatting wiring) gets exercised -- no test_pipeline_graph.py test
    invokes build_pipeline_graph() at all, they call each node as a bare
    function directly."""

    async def test_tool_result_reaches_the_final_reply(self) -> None:
        state = _make_state("Where's my order #12345?")
        fake_tenant = type(
            "Tenant",
            (),
            {
                "closing_action": "escalate_to_human",
                "behavior_config": {
                    "tool_calling": {"order_status_lookup_enabled": True}
                },
            },
        )()
        tool_call = ToolCallRequest(name="order_status_lookup", args={"order_number": "12345"})
        with (
            patch(
                "app.pipeline.graph.generate_text",
                side_effect=["knowledge_question", "cold", "ANSWERED\nHere's your update!"],
            ) as mock_generate_text,
            patch(
                "app.pipeline.graph.generate_with_tools", return_value=(None, [tool_call])
            ) as mock_tools,
            patch("app.pipeline.graph.embed_text", return_value=[0.1]),
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_knowledge_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
        ):
            mock_knowledge_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_message_repo_cls.return_value.list_by_conversation = AsyncMock(
                return_value=[]
            )
            result = await run_pipeline(state, AsyncMock(), InMemorySaver())

        mock_tools.assert_called_once()
        assert result["draft_text"] == "Here's your update!"
        # keep_chatting is the 3rd generate_text call (understand_intent,
        # score_lead, keep_chatting) -- its prompt must actually contain
        # the fake connector's (deterministic) formatted result, not just
        # "some prompt or other" that happens to get a mocked reply back.
        keep_chatting_prompt = mock_generate_text.call_args_list[2].args[0]
        assert "Order 12345 status:" in keep_chatting_prompt

    async def test_tool_calling_off_by_default_never_calls_generate_with_tools(self) -> None:
        state = _make_state("What flavors do you have?")
        with (
            patch("app.pipeline.graph.generate_text", return_value="cold"),
            patch("app.pipeline.graph.generate_with_tools") as mock_tools,
            patch("app.pipeline.graph.embed_text", return_value=[0.1]),
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_knowledge_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_tenant_repo_cls.return_value.get = AsyncMock(
                return_value=type("Tenant", (), {"behavior_config": {}})()
            )
            mock_knowledge_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            await run_pipeline(state, AsyncMock(), InMemorySaver())

        mock_tools.assert_not_called()


class TestResumePipeline:
    async def test_resume_completes_the_run_and_logs(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my allergy?")
        checkpointer = InMemorySaver()
        session = AsyncMock()
        with (
            patch("app.pipeline.graph.generate_text", return_value="other"),
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
        ):
            mock_tenant_repo_cls.return_value.get = AsyncMock(
                return_value=type("Tenant", (), {"behavior_config": {}})()
            )
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_message_repo_cls.return_value.list_by_conversation = AsyncMock(
                return_value=[]
            )

            first = await run_pipeline(state, session, checkpointer)
            assert "__interrupt__" in first

            resumed = await resume_pipeline(
                state.conversation_id, {"approved": True}, session, checkpointer
            )

        assert "__interrupt__" not in resumed
        mock_lead_repo_cls.return_value.add.assert_called_once()
        # Logged once, by decide_next_step at pause time -- log_lead_and_notify
        # sees state.escalation_logged=True on resume and skips its own add
        # (PipelineState.escalation_logged's own docstring; fixes the
        # double-log gap this test used to pin).
        mock_escalation_repo_cls.return_value.add.assert_called_once()
        logged_escalation = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged_escalation.status == "pending"

    async def test_separate_conversations_dont_share_paused_state(self) -> None:
        state_a = _make_state("Can you guarantee this will definitely cure my allergy?")
        state_b = _make_state("Can you guarantee this will definitely cure my rash?")
        checkpointer = InMemorySaver()
        with (
            patch("app.pipeline.graph.generate_text", return_value="other"),
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
        ):
            mock_tenant_repo_cls.return_value.get = AsyncMock(
                return_value=type("Tenant", (), {"behavior_config": {}})()
            )
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            mock_message_repo_cls.return_value.add = AsyncMock()
            mock_message_repo_cls.return_value.list_by_conversation = AsyncMock(
                return_value=[]
            )
            result_a = await run_pipeline(state_a, AsyncMock(), checkpointer)
            result_b = await run_pipeline(state_b, AsyncMock(), checkpointer)

        assert "__interrupt__" in result_a
        assert "__interrupt__" in result_b
        assert result_a["conversation_id"] != result_b["conversation_id"]


class TestPublishPipelineEvents:
    """docs/ROADMAP.md §3.5 -- called by the caller (Celery task / Test
    Console endpoint) after its own session.commit(), never from inside a
    graph node (see the function's own docstring for why). These tests
    exercise result-shape interpretation only, not the real pub/sub --
    app/core/events.py's publish_event is mocked throughout."""

    async def test_interrupted_result_publishes_only_an_escalation_event(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my allergy?")
        result = {
            "__interrupt__": [Interrupt(value={"escalation_reason": "safety floor hit"})],
            "decision": "escalate_to_human",
        }
        with patch("app.pipeline.runner.publish_event") as mock_publish:
            await publish_pipeline_events(state, result)

        mock_publish.assert_called_once_with(
            state.tenant_id,
            {
                "type": "escalation",
                "channel_type": state.channel_type,
                "conversation_id": str(state.conversation_id),
                "reason": "safety floor hit",
            },
        )

    async def test_book_or_checkout_fallback_publishes_both_events(self) -> None:
        # decide_next_step/book_or_checkout's missing-closing_link fallback
        # (graph.py) is the one case that sets BOTH decision=
        # escalate_to_human AND draft_text in the same run, unlike the two
        # interrupt()-based escalations, which only ever set one or the
        # other -- both events must fire, not just one.
        state = _make_state("I'd like to book now")
        result = {
            "decision": "escalate_to_human",
            "escalation_reason": "book_or_checkout: tenant has no closing_link configured",
            "draft_text": "Someone will follow up shortly to complete this.",
        }
        with patch("app.pipeline.runner.publish_event") as mock_publish:
            await publish_pipeline_events(state, result)

        assert mock_publish.call_count == 2
        published_types = {call.args[1]["type"] for call in mock_publish.call_args_list}
        assert published_types == {"escalation", "message"}

    async def test_normal_reply_publishes_only_a_message_event(self) -> None:
        state = _make_state("Do you ship internationally?")
        result = {"decision": "keep_chatting", "draft_text": "Yes, we ship worldwide!"}
        with patch("app.pipeline.runner.publish_event") as mock_publish:
            await publish_pipeline_events(state, result)

        mock_publish.assert_called_once_with(
            state.tenant_id,
            {
                "type": "message",
                "channel_type": state.channel_type,
                "conversation_id": str(state.conversation_id),
            },
        )

    async def test_no_draft_and_no_escalation_publishes_nothing(self) -> None:
        state = _make_state("hi")
        result = {"decision": "keep_chatting", "draft_text": None}
        with patch("app.pipeline.runner.publish_event") as mock_publish:
            await publish_pipeline_events(state, result)

        mock_publish.assert_not_called()
