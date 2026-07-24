import uuid
from unittest.mock import AsyncMock, patch

from langgraph.runtime import Runtime

from app.pipeline.context import PipelineContext
from app.pipeline.graph import (
    book_or_checkout,
    decide_next_step,
    keep_chatting,
    log_lead_and_notify,
    route_after_decision,
    score_lead,
    search_knowledge,
    understand_intent,
)
from app.pipeline.state import PipelineState


def _make_state(text: str) -> PipelineState:
    return PipelineState(
        tenant_id=uuid.uuid4(), conversation_id=uuid.uuid4(), incoming_text=text
    )


def _make_runtime() -> Runtime[PipelineContext]:
    # The session itself is never touched here -- TenantTriggerPhraseRepository
    # is mocked at the module level in each test below, so this just needs to
    # satisfy PipelineContext's type, not behave like a real AsyncSession.
    return Runtime(context=PipelineContext(session=AsyncMock()))


class TestUnderstandIntent:
    def test_uses_model_label_when_valid(self) -> None:
        state = _make_state("What flavors of honey do you have?")
        with patch("app.pipeline.graph.generate_text", return_value="knowledge_question"):
            result = understand_intent(state)
        assert result.detected_intent == "knowledge_question"

    def test_is_case_and_whitespace_insensitive(self) -> None:
        state = _make_state("Merhaba!")
        with patch("app.pipeline.graph.generate_text", return_value="  Small_Talk  \n"):
            result = understand_intent(state)
        assert result.detected_intent == "small_talk"

    def test_falls_back_to_other_on_unrecognized_label(self) -> None:
        state = _make_state("asdkjasndkjan")
        with patch("app.pipeline.graph.generate_text", return_value="not a real label"):
            result = understand_intent(state)
        assert result.detected_intent == "other"


class TestSearchKnowledge:
    async def test_populates_retrieved_chunks_from_repository(self) -> None:
        state = _make_state("Do you ship internationally?")
        fake_chunks = [
            type("Chunk", (), {"content": "We ship worldwide via DHL."})(),
            type("Chunk", (), {"content": "Shipping takes 3-5 business days."})(),
        ]
        with (
            patch("app.pipeline.graph.embed_text", return_value=[0.1, 0.2, 0.3]),
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.search_similar = AsyncMock(return_value=fake_chunks)
            result = await search_knowledge(state, _make_runtime())
        assert result.retrieved_chunks == [
            "We ship worldwide via DHL.",
            "Shipping takes 3-5 business days.",
        ]

    async def test_empty_when_no_chunks_match(self) -> None:
        state = _make_state("Do you ship internationally?")
        with (
            patch("app.pipeline.graph.embed_text", return_value=[0.1, 0.2, 0.3]),
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            result = await search_knowledge(state, _make_runtime())
        assert result.retrieved_chunks == []

    async def test_uses_retrieval_query_task_type(self) -> None:
        state = _make_state("Do you ship internationally?")
        with (
            patch("app.pipeline.graph.embed_text", return_value=[0.1]) as mock_embed,
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            await search_knowledge(state, _make_runtime())
        mock_embed.assert_called_once_with(state.incoming_text, task_type="RETRIEVAL_QUERY")


class TestScoreLead:
    def test_uses_model_label_when_valid(self) -> None:
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        with patch("app.pipeline.graph.generate_text", return_value="hot"):
            result = score_lead(state)
        assert result.lead_score == "hot"

    def test_is_case_and_whitespace_insensitive(self) -> None:
        state = _make_state("Just curious what you sell")
        with patch("app.pipeline.graph.generate_text", return_value="  Cold  \n"):
            result = score_lead(state)
        assert result.lead_score == "cold"

    def test_falls_back_to_cold_on_unrecognized_label(self) -> None:
        state = _make_state("asdkjasndkjan")
        with patch("app.pipeline.graph.generate_text", return_value="not a real label"):
            result = score_lead(state)
        assert result.lead_score == "cold"


class TestDecideNextStepSafetyFloor:
    async def test_escalates_on_system_default_trigger_without_tenant_phrases(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my condition?")
        with patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert route_after_decision(result) == "escalate_to_human"

    async def test_escalates_on_tenant_added_phrase(self) -> None:
        state = _make_state("Do you sell mad honey?")
        fake_row = type("Row", (), {"phrase": "mad honey"})()
        with patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list = AsyncMock(return_value=[fake_row])
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert "mad honey" in result.escalation_reason


class TestDecideNextStepRouting:
    async def test_keeps_chatting_when_not_hot_purchase_intent(self) -> None:
        state = _make_state("What flavors of honey do you have?")
        state.detected_intent = "knowledge_question"
        state.lead_score = "warm"
        with patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "keep_chatting"

    async def test_keeps_chatting_when_hot_but_not_purchase_intent(self) -> None:
        state = _make_state("This arrived broken, I'm furious")
        state.detected_intent = "complaint_or_problem"
        state.lead_score = "hot"
        with patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "keep_chatting"

    async def test_uses_tenant_closing_action_when_hot_purchase_intent(self) -> None:
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        state.detected_intent = "purchase_intent"
        state.lead_score = "hot"
        fake_tenant = type("Tenant", (), {"closing_action": "book_or_checkout"})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "book_or_checkout"

    async def test_defaults_to_escalate_when_tenant_row_missing(self) -> None:
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        state.detected_intent = "purchase_intent"
        state.lead_score = "hot"
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=None)
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"


class TestKeepChatting:
    def test_sets_draft_text_from_model_response(self) -> None:
        state = _make_state("Do you ship internationally?")
        state.retrieved_chunks = ["We ship worldwide via DHL."]
        with patch(
            "app.pipeline.graph.generate_text", return_value="Yes, we ship worldwide!"
        ):
            result = keep_chatting(state)
        assert result.draft_text == "Yes, we ship worldwide!"

    def test_handles_no_retrieved_chunks_without_erroring(self) -> None:
        state = _make_state("Do you ship internationally?")
        state.retrieved_chunks = []
        with patch(
            "app.pipeline.graph.generate_text", return_value="Let me check on that."
        ) as mock_gen:
            result = keep_chatting(state)
        assert result.draft_text == "Let me check on that."
        prompt = mock_gen.call_args.args[0]
        assert "no matching knowledge found" in prompt


class TestLogLeadAndNotify:
    async def test_always_logs_a_lead(self) -> None:
        state = _make_state("What flavors do you have?")
        state.detected_intent = "knowledge_question"
        state.lead_score = "cold"
        state.decision = "keep_chatting"
        with (
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            await log_lead_and_notify(state, _make_runtime())

        mock_lead_repo_cls.return_value.add.assert_called_once()
        logged_lead = mock_lead_repo_cls.return_value.add.call_args.args[0]
        assert logged_lead.score == "cold"
        assert logged_lead.tenant_id == state.tenant_id
        assert logged_lead.conversation_id == state.conversation_id
        mock_escalation_repo_cls.return_value.add.assert_not_called()

    async def test_logs_an_escalation_when_escalated(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my condition?")
        state.lead_score = "warm"
        state.decision = "escalate_to_human"
        state.escalation_reason = "contraindication language (matched 'allerg')"
        with (
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            await log_lead_and_notify(state, _make_runtime())

        mock_escalation_repo_cls.return_value.add.assert_called_once()
        logged_escalation = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged_escalation.reason == state.escalation_reason
        assert logged_escalation.layer == "platform_floor"
        assert logged_escalation.status == "pending"

    async def test_does_not_log_escalation_without_a_reason(self) -> None:
        # Shouldn't happen in practice (decide_next_step always sets a
        # reason alongside escalate_to_human), but guards against a
        # constraint violation if it ever did.
        state = _make_state("hello")
        state.lead_score = "cold"
        state.decision = "escalate_to_human"
        state.escalation_reason = None
        with (
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            await log_lead_and_notify(state, _make_runtime())

        mock_escalation_repo_cls.return_value.add.assert_not_called()


class TestBookOrCheckout:
    async def test_includes_the_tenant_closing_link(self) -> None:
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        fake_tenant = type("Tenant", (), {"closing_link": "https://pay.example.com/honey"})()
        with (
            patch("app.pipeline.graph.TenantRepository") as mock_repo_cls,
            patch(
                "app.pipeline.graph.generate_text",
                return_value="Here you go! https://pay.example.com/honey",
            ) as mock_gen,
        ):
            mock_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            result = await book_or_checkout(state, _make_runtime())

        assert result.draft_text == "Here you go! https://pay.example.com/honey"
        assert result.decision != "escalate_to_human"
        prompt = mock_gen.call_args.args[0]
        assert "https://pay.example.com/honey" in prompt

    async def test_downgrades_to_escalation_when_no_link_configured(self) -> None:
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        fake_tenant = type("Tenant", (), {"closing_link": None})()
        with (
            patch("app.pipeline.graph.TenantRepository") as mock_repo_cls,
            patch("app.pipeline.graph.generate_text", return_value="Someone will follow up!"),
        ):
            mock_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            result = await book_or_checkout(state, _make_runtime())

        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert "closing_link" in result.escalation_reason
        assert result.draft_text == "Someone will follow up!"

    async def test_downgrades_to_escalation_when_tenant_row_missing(self) -> None:
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        with (
            patch("app.pipeline.graph.TenantRepository") as mock_repo_cls,
            patch("app.pipeline.graph.generate_text", return_value="Someone will follow up!"),
        ):
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            result = await book_or_checkout(state, _make_runtime())

        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
