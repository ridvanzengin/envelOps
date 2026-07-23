import uuid
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import InMemorySaver

from app.pipeline.runner import resume_pipeline, run_pipeline
from app.pipeline.state import PipelineState

# LangGraph's in-memory checkpointer runs the identical interrupt/resume
# mechanics as the real Postgres-backed one (docs/ARCHITECTURE.md §5) --
# only the storage differs, so this is a legitimate way to test the pause/
# resume cycle fast and without needing a real database, not a stand-in
# that skips the thing actually being tested. The real backend was smoke-
# tested separately against Postgres (see PR description).


def _make_state(text: str) -> PipelineState:
    return PipelineState(
        tenant_id=uuid.uuid4(), conversation_id=uuid.uuid4(), incoming_text=text
    )


class TestRunPipelinePauses:
    async def test_pauses_at_escalate_to_human_on_safety_trigger(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my allergy?")
        with (
            patch("app.pipeline.graph.generate_text", return_value="other"),
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            result = await run_pipeline(state, AsyncMock(), InMemorySaver())

        assert "__interrupt__" in result
        assert result["decision"] == "escalate_to_human"
        interrupt = result["__interrupt__"][0]
        assert interrupt.value["conversation_id"] == str(state.conversation_id)
        assert interrupt.value["escalation_reason"] is not None

    async def test_does_not_pause_on_an_ordinary_message(self) -> None:
        state = _make_state("What flavors do you have?")
        with (
            patch("app.pipeline.graph.generate_text", return_value="cold"),
            patch("app.pipeline.graph.embed_text", return_value=[0.1]),
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_knowledge_repo_cls,
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_knowledge_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            result = await run_pipeline(state, AsyncMock(), InMemorySaver())

        assert "__interrupt__" not in result
        assert result["decision"] == "keep_chatting"


class TestResumePipeline:
    async def test_resume_completes_the_run_and_logs(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my allergy?")
        checkpointer = InMemorySaver()
        session = AsyncMock()
        with (
            patch("app.pipeline.graph.generate_text", return_value="other"),
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()

            first = await run_pipeline(state, session, checkpointer)
            assert "__interrupt__" in first

            resumed = await resume_pipeline(
                state.conversation_id, {"approved": True}, session, checkpointer
            )

        assert "__interrupt__" not in resumed
        mock_lead_repo_cls.return_value.add.assert_called_once()
        mock_escalation_repo_cls.return_value.add.assert_called_once()
        logged_escalation = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged_escalation.status == "pending"

    async def test_separate_conversations_dont_share_paused_state(self) -> None:
        state_a = _make_state("Can you guarantee this will definitely cure my allergy?")
        state_b = _make_state("Can you guarantee this will definitely cure my rash?")
        checkpointer = InMemorySaver()
        with (
            patch("app.pipeline.graph.generate_text", return_value="other"),
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            result_a = await run_pipeline(state_a, AsyncMock(), checkpointer)
            result_b = await run_pipeline(state_b, AsyncMock(), checkpointer)

        assert "__interrupt__" in result_a
        assert "__interrupt__" in result_b
        assert result_a["conversation_id"] != result_b["conversation_id"]
