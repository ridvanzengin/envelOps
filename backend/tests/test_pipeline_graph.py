import uuid
from unittest.mock import patch

import pytest

from app.pipeline.graph import decide_next_step, route_after_decision, understand_intent
from app.pipeline.state import PipelineState


def _make_state(text: str) -> PipelineState:
    return PipelineState(
        tenant_id=uuid.uuid4(), conversation_id=uuid.uuid4(), incoming_text=text
    )


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


class TestDecideNextStepSafetyFloor:
    def test_escalates_on_safety_trigger_without_calling_llm(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my condition?")
        result = decide_next_step(state)
        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert route_after_decision(result) == "escalate_to_human"

    def test_raises_not_implemented_past_the_safety_floor(self) -> None:
        state = _make_state("What flavors of honey do you have?")
        with pytest.raises(NotImplementedError):
            decide_next_step(state)
