import uuid
from unittest.mock import AsyncMock, patch

from langgraph.runtime import Runtime

from app.pipeline.context import PipelineContext
from app.pipeline.graph import (
    book_or_checkout,
    decide_next_step,
    keep_chatting,
    load_history,
    log_lead_and_notify,
    route_after_decision,
    score_lead,
    search_knowledge,
    understand_intent,
)
from app.pipeline.state import PipelineState


def _make_state(text: str) -> PipelineState:
    return PipelineState(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        incoming_text=text,
        channel_type="telegram",
    )


def _make_runtime() -> Runtime[PipelineContext]:
    # The session itself is never touched here -- TenantTriggerPhraseRepository
    # is mocked at the module level in each test below, so this just needs to
    # satisfy PipelineContext's type, not behave like a real AsyncSession.
    return Runtime(context=PipelineContext(session=AsyncMock()))


def _fake_message(direction: str, text: str) -> object:
    return type("Msg", (), {"direction": direction, "text": text})()


class TestLoadHistory:
    async def test_excludes_the_current_message_and_formats_the_rest(self) -> None:
        state = _make_state("How much for 6 jars?")
        stored = [
            _fake_message("inbound", "Do you ship to Canada?"),
            _fake_message("outbound", "Yes, we do!"),
            _fake_message("inbound", "How much for 6 jars?"),  # the current message
        ]
        with patch("app.pipeline.graph.MessageRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list_by_conversation = AsyncMock(return_value=stored)
            result = await load_history(state, _make_runtime())
        assert result.conversation_history == [
            "Customer: Do you ship to Canada?",
            "You: Yes, we do!",
        ]

    async def test_empty_for_a_conversations_first_message(self) -> None:
        state = _make_state("Hello")
        stored = [_fake_message("inbound", "Hello")]  # only the current message so far
        with patch("app.pipeline.graph.MessageRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list_by_conversation = AsyncMock(return_value=stored)
            result = await load_history(state, _make_runtime())
        assert result.conversation_history == []

    async def test_caps_at_history_max_messages(self) -> None:
        state = _make_state("latest")
        stored = [_fake_message("inbound", f"msg {i}") for i in range(20)] + [
            _fake_message("inbound", "latest")
        ]
        with patch("app.pipeline.graph.MessageRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list_by_conversation = AsyncMock(return_value=stored)
            result = await load_history(state, _make_runtime())
        assert len(result.conversation_history) == 10
        assert result.conversation_history[-1] == "Customer: msg 19"
        assert result.conversation_history[0] == "Customer: msg 10"


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

    def test_includes_conversation_history_when_present(self) -> None:
        state = _make_state("How much for 6 jars?")
        state.conversation_history = [
            "Customer: Do you ship to Canada?",
            "You: Yes, we do!",
        ]
        with patch(
            "app.pipeline.graph.generate_text", return_value="purchase_intent"
        ) as mock_gen:
            understand_intent(state)
        prompt = mock_gen.call_args.args[0]
        assert "Earlier in this conversation" in prompt
        assert "Do you ship to Canada?" in prompt

    def test_omits_history_block_for_a_conversations_first_message(self) -> None:
        state = _make_state("Hello")
        with patch("app.pipeline.graph.generate_text", return_value="small_talk") as mock_gen:
            understand_intent(state)
        prompt = mock_gen.call_args.args[0]
        assert "Earlier in this conversation" not in prompt


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

    def test_includes_conversation_history_when_present(self) -> None:
        state = _make_state("Let's do it")
        state.conversation_history = [
            "Customer: How much for 6 jars?",
            "You: $50 total for 6!",
        ]
        with patch("app.pipeline.graph.generate_text", return_value="hot") as mock_gen:
            score_lead(state)
        prompt = mock_gen.call_args.args[0]
        assert "Earlier in this conversation" in prompt
        assert "How much for 6 jars?" in prompt


class TestDecideNextStepSafetyFloor:
    async def test_escalates_on_system_default_trigger_without_tenant_phrases(self) -> None:
        state = _make_state("Can you guarantee this will definitely cure my condition?")
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert result.escalation_logged is True
        assert route_after_decision(result) == "escalate_to_human"
        mock_escalation_repo_cls.return_value.add.assert_called_once()
        logged = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged.status == "pending"
        assert logged.layer == "platform_floor"

    async def test_escalates_on_tenant_added_phrase(self) -> None:
        state = _make_state("Do you sell mad honey?")
        fake_row = type("Row", (), {"phrase": "mad honey"})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[fake_row])
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert "mad honey" in result.escalation_reason
        assert result.escalation_logged is True
        mock_escalation_repo_cls.return_value.add.assert_called_once()


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
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=None)
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"
        assert result.escalation_logged is True

    async def test_logs_escalation_when_tenant_closing_action_is_escalate_to_human(
        self,
    ) -> None:
        # Real bug, found via Test Console: closing_action defaults to
        # escalate_to_human for every tenant that hasn't opted into
        # book_or_checkout (Tenant.closing_action's own docstring), and
        # this path used to route straight to escalate_to_human's
        # interrupt() without ever logging an Escalation -- silently
        # pausing forever with no way for a human to ever see or resolve
        # it. The synthetic test tenant always sets closing_action=
        # book_or_checkout, so synthetic testing never exercised this.
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        state.detected_intent = "purchase_intent"
        state.lead_score = "hot"
        fake_tenant = type("Tenant", (), {"closing_action": "escalate_to_human"})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())

        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert result.escalation_logged is True
        logged = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged.reason == result.escalation_reason
        assert logged.layer == "business_rule"
        assert logged.status == "pending"


class TestKeepChatting:
    def test_sets_draft_text_from_model_response(self) -> None:
        state = _make_state("Do you ship internationally?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["We ship worldwide via DHL."]
        with patch(
            "app.pipeline.graph.generate_text", return_value="Yes, we ship worldwide!"
        ):
            result = keep_chatting(state)
        assert result.draft_text == "Yes, we ship worldwide!"

    def test_handles_no_retrieved_chunks_without_erroring(self) -> None:
        state = _make_state("Do you ship internationally?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = []
        with patch(
            "app.pipeline.graph.generate_text", return_value="Let me check on that."
        ) as mock_gen:
            result = keep_chatting(state)
        assert result.draft_text == "Let me check on that."
        prompt = mock_gen.call_args.args[0]
        assert "no matching knowledge found" in prompt

    def test_grounds_reply_for_information_seeking_intents(self) -> None:
        # knowledge_question/purchase_intent/complaint_or_problem all get
        # the strict "don't guess" grounding instruction + the knowledge
        # block -- there's a real question to ground an answer in.
        for intent in ("knowledge_question", "purchase_intent", "complaint_or_problem"):
            state = _make_state("Do you ship internationally?")
            state.detected_intent = intent
            state.retrieved_chunks = ["We ship worldwide via DHL."]
            with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
                keep_chatting(state)
            prompt = mock_gen.call_args.args[0]
            assert "Ground your reply ONLY in the knowledge" in prompt
            assert "We ship worldwide via DHL." in prompt

    def test_skips_grounding_for_small_talk_and_other(self) -> None:
        # Found via real usage, not synthetic testing: a bare greeting
        # ("merhaba") or a "you there?" check-in isn't asking anything, so
        # forcing the "I don't have that information" disclaimer onto it
        # was a real bug -- these intents get a plain conversational
        # instruction instead, with no knowledge block at all.
        for intent in ("small_talk", "other"):
            state = _make_state("hi")
            state.detected_intent = intent
            state.retrieved_chunks = ["We ship worldwide via DHL."]
            with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
                keep_chatting(state)
            prompt = mock_gen.call_args.args[0]
            assert "Ground your reply ONLY in the knowledge" not in prompt
            assert "isn't asking a specific question" in prompt
            # The knowledge block itself shouldn't leak into a greeting reply.
            assert "We ship worldwide via DHL." not in prompt

    def test_includes_history_and_continuation_instruction_when_present(self) -> None:
        state = _make_state("What about shipping?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["We ship worldwide via DHL."]
        state.conversation_history = ["Customer: Hi!", "You: Hey there!"]
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            keep_chatting(state)
        prompt = mock_gen.call_args.args[0]
        assert "Earlier in this conversation" in prompt
        assert "Hey there!" in prompt
        assert "continuation of an ongoing conversation" in prompt

    def test_omits_continuation_instruction_for_a_conversations_first_message(self) -> None:
        state = _make_state("hi")
        state.detected_intent = "small_talk"
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            keep_chatting(state)
        prompt = mock_gen.call_args.args[0]
        assert "Earlier in this conversation" not in prompt
        assert "continuation of an ongoing conversation" not in prompt

    def test_grounding_instruction_includes_clarifying_question_branch(self) -> None:
        # docs/ROADMAP.md §3.2 -- an ambiguous knowledge_question ("kırmızı
        # var mı?" with no product named) should be able to get exactly one
        # clarifying question instead of always falling to the "I don't
        # have that information" disclaimer. This only checks the
        # instruction reaches the model; the model's actual judgment call
        # isn't something a unit test can exercise.
        state = _make_state("kırmızı var mı?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["Available colors: blue, green, black."]
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            keep_chatting(state)
        prompt = mock_gen.call_args.args[0]
        assert "ask exactly ONE short, natural clarifying question" in prompt
        assert "not an escalation" in prompt

    def test_clarifying_question_branch_not_offered_for_small_talk(self) -> None:
        # Small talk/other still skip the whole grounding instruction (no
        # question was asked at all), so the clarifying-question branch
        # shouldn't leak in there either.
        state = _make_state("hi")
        state.detected_intent = "small_talk"
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            keep_chatting(state)
        prompt = mock_gen.call_args.args[0]
        assert "clarifying question" not in prompt

    def test_prior_clarifying_question_is_visible_in_history_for_the_followup(self) -> None:
        # The mechanism that keeps this to *exactly* one question: if the
        # model already asked one last turn, it's right there in the
        # history block, so the customer's follow-up reply lands in
        # branch 2/3 of the instruction instead of triggering another ask.
        state = _make_state("kırmızısı")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["Available colors: blue, green, black."]
        state.conversation_history = ["Customer: kırmızı var mı?", "You: neyin kırmızısı?"]
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            keep_chatting(state)
        prompt = mock_gen.call_args.args[0]
        assert "neyin kırmızısı?" in prompt


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

    async def test_does_not_log_escalation_again_when_already_logged(self) -> None:
        # decide_next_step's safety-floor branch logs the Escalation itself
        # and sets escalation_logged=True before the pause; resuming past
        # that pause (POST /escalations/{id}/resolve) must not log it a
        # second time here.
        state = _make_state("Can you guarantee this will definitely cure my condition?")
        state.lead_score = "warm"
        state.decision = "escalate_to_human"
        state.escalation_reason = "contraindication language (matched 'allerg')"
        state.escalation_logged = True
        with (
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
        ):
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock()
            await log_lead_and_notify(state, _make_runtime())

        mock_lead_repo_cls.return_value.add.assert_called_once()
        mock_escalation_repo_cls.return_value.add.assert_not_called()

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

    async def test_includes_conversation_history_when_present(self) -> None:
        state = _make_state("Let's do it")
        state.conversation_history = ["Customer: How much for 6 jars?", "You: $50 total!"]
        fake_tenant = type("Tenant", (), {"closing_link": "https://pay.example.com/honey"})()
        with (
            patch("app.pipeline.graph.TenantRepository") as mock_repo_cls,
            patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen,
        ):
            mock_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            await book_or_checkout(state, _make_runtime())

        prompt = mock_gen.call_args.args[0]
        assert "Earlier in this conversation" in prompt
        assert "How much for 6 jars?" in prompt

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
