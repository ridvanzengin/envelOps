import uuid
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.runtime import Runtime

from app.pipeline.context import PipelineContext
from app.pipeline.graph import (
    decide_next_step,
    route_after_decision,
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

    async def test_raises_not_implemented_past_the_safety_floor(self) -> None:
        state = _make_state("What flavors of honey do you have?")
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls,
            pytest.raises(NotImplementedError),
        ):
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            await decide_next_step(state, _make_runtime())
