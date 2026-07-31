import uuid
from unittest.mock import AsyncMock, patch

from langgraph.runtime import Runtime

from app.core.llm import ToolCallRequest
from app.pipeline.context import PipelineContext
from app.pipeline.graph import (
    _clean_reason_for_display,
    book_or_checkout,
    call_tools,
    check_pending_escalation,
    decide_next_step,
    keep_chatting,
    load_history,
    load_tenant_config,
    log_lead_and_notify,
    route_after_decision,
    route_after_escalation_check,
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


class TestLoadTenantConfig:
    async def test_stashes_the_tenants_raw_behavior_config_dict(self) -> None:
        state = _make_state("hi")
        fake_tenant = type(
            "Tenant", (), {"behavior_config": {"greeting": {"tone": "formal_business"}}}
        )()
        with patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls:
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            result = await load_tenant_config(state, _make_runtime())
        assert result.tenant_behavior_config == {"greeting": {"tone": "formal_business"}}

    async def test_missing_tenant_row_defaults_to_empty_dict(self) -> None:
        # Shouldn't be possible in practice (state.tenant_id comes from an
        # already-authenticated context), but a missing row must not crash
        # this node -- every downstream load_tenant_behavior_config() call
        # already treats {} as "all defaults."
        state = _make_state("hi")
        with patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls:
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=None)
            result = await load_tenant_config(state, _make_runtime())
        assert result.tenant_behavior_config == {}


class TestCheckPendingEscalation:
    """docs/ROADMAP.md §3.1 -- closes a real gap: run_pipeline() called
    again on an already-escalated conversation doesn't resume/no-op, it
    silently starts a fresh run (empirically verified separately). This
    node/edge is what stops that fresh run from doing anything."""

    async def test_routes_to_continue_when_nothing_pending(self) -> None:
        state = _make_state("Do you ship to Canada?")
        with patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls:
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=None
            )
            result = await check_pending_escalation(state, _make_runtime())
        assert result.already_escalated is False
        assert route_after_escalation_check(result) == "continue"

    async def test_routes_to_skip_when_a_blocking_escalation_is_pending(self) -> None:
        state = _make_state("Any update?")
        fake_escalation = type("Escalation", (), {"id": uuid.uuid4()})()
        with patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls:
            mock_escalation_repo_cls.return_value.get_pending_by_conversation = AsyncMock(
                return_value=fake_escalation
            )
            result = await check_pending_escalation(state, _make_runtime())
        assert result.already_escalated is True
        assert route_after_escalation_check(result) == "skip"


class TestCleanReasonForDisplay:
    def test_strips_matched_pattern_suffix(self) -> None:
        assert (
            _clean_reason_for_display("contraindication language (matched '\\ballerg\\b')")
            == "contraindication language"
        )

    def test_strips_certainty_efficacy_suffix(self) -> None:
        assert (
            _clean_reason_for_display(
                "outcome-guarantee request (certainty 'guarantee' + efficacy 'cure')"
            )
            == "outcome-guarantee request"
        )

    def test_strips_tenant_phrase_suffix(self) -> None:
        assert (
            _clean_reason_for_display("tenant-defined trigger phrase (matched 'mad honey')")
            == "tenant-defined trigger phrase"
        )

    def test_leaves_a_reason_with_no_parenthetical_unchanged(self) -> None:
        reason = "book_or_checkout: tenant has no closing_link configured"
        assert _clean_reason_for_display(reason) == reason


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

    def test_prompt_distinguishes_existing_order_changes_from_new_purchases(self) -> None:
        # docs/ROADMAP.md calibration finding: "swap an article of order
        # #12345" (an existing-order request) was classified as
        # purchase_intent, which routed it to book_or_checkout and sent a
        # fresh checkout link instead of grounding it against the
        # tenant's actual order-change policy. knowledge_question's
        # definition now explicitly carves out modify/cancel/exchange
        # requests on an order the customer already placed, and
        # purchase_intent is explicitly scoped to a NEW purchase.
        state = _make_state("Can you swap an article of order #12345?")
        with patch(
            "app.pipeline.graph.generate_text", return_value="knowledge_question"
        ) as mock_gen:
            understand_intent(state)
        prompt = mock_gen.call_args.args[0]
        assert "modify, cancel, exchange, or" in prompt
        assert "something NEW" in prompt


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

    async def test_passes_the_tenants_not_found_max_distance_through(self) -> None:
        # docs/ROADMAP.md §3.6 -- the root-cause fix for the out-of-domain
        # clarify-loop bug: a tenant's configured threshold must actually
        # reach search_similar, not just exist in the schema.
        state = _make_state("Do you ship internationally?")
        state.tenant_behavior_config = {"knowledge_query": {"not_found_max_distance": 0.5}}
        with (
            patch("app.pipeline.graph.embed_text", return_value=[0.1, 0.2, 0.3]),
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            await search_knowledge(state, _make_runtime())
        call_kwargs = mock_repo_cls.return_value.search_similar.call_args.kwargs
        assert call_kwargs["max_distance"] == 0.5

    async def test_defaults_to_no_max_distance_when_tenant_has_no_config(self) -> None:
        state = _make_state("Do you ship internationally?")
        with (
            patch("app.pipeline.graph.embed_text", return_value=[0.1, 0.2, 0.3]),
            patch("app.pipeline.graph.KnowledgeChunkRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.search_similar = AsyncMock(return_value=[])
            await search_knowledge(state, _make_runtime())
        call_kwargs = mock_repo_cls.return_value.search_similar.call_args.kwargs
        assert call_kwargs["max_distance"] is None

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
        fake_escalation = type("Escalation", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
            patch(
                "app.pipeline.graph.generate_text",
                return_value="Let me check with a colleague and get back to you!",
            ),
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert result.escalation_logged is True
        assert route_after_decision(result) == "escalate_to_human"
        mock_escalation_repo_cls.return_value.add.assert_called_once()
        logged = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged.status == "pending"
        assert logged.layer == "platform_floor"
        # docs/ROADMAP.md §3.1 -- a natural cover reply instead of silence,
        # sent the same way any other reply is (state.draft_text).
        assert result.draft_text == "Let me check with a colleague and get back to you!"
        # ...plus an internal-only note explaining why, written directly
        # here (same pattern as the Escalation row above), tied to the
        # escalation it explains and with the raw regex pattern cleaned
        # out of the display text.
        mock_message_repo_cls.return_value.add.assert_called_once()
        note = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert note.audience == "internal"
        assert note.escalation_id == fake_escalation.id
        assert note.direction == "outbound"
        assert "(matched" not in note.text
        assert "(certainty" not in note.text
        assert "outcome-guarantee request" in note.text

    async def test_escalates_on_tenant_added_phrase(self) -> None:
        state = _make_state("Do you sell mad honey?")
        fake_row = type("Row", (), {"phrase": "mad honey"})()
        fake_escalation = type("Escalation", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.graph.generate_text", return_value="x"),
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[fake_row])
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert "mad honey" in result.escalation_reason
        assert result.escalation_logged is True
        mock_escalation_repo_cls.return_value.add.assert_called_once()
        assert result.draft_text == "x"
        note = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert note.escalation_id == fake_escalation.id


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
        fake_escalation = type("Escalation", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.graph.generate_text", return_value="x"),
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=None)
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"
        assert result.escalation_logged is True
        assert result.draft_text == "x"
        mock_message_repo_cls.return_value.add.assert_called_once()

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
        fake_escalation = type("Escalation", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.graph.generate_text", return_value="x"),
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())

        assert result.decision == "escalate_to_human"
        assert result.escalation_reason is not None
        assert result.escalation_logged is True
        logged = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged.reason == result.escalation_reason
        assert logged.layer == "business_rule"
        assert logged.status == "pending"
        assert result.draft_text == "x"
        note = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert note.escalation_id == fake_escalation.id
        assert note.audience == "internal"

    async def test_hot_lead_requires_purchase_intent_false_widens_the_gate(self) -> None:
        # docs/ROADMAP.md §3.6 -- Vertex Growth Partners (B2B, "almost
        # always human-closed" per REQUIREMENTS §2) wants ANY hot lead
        # routed toward closing, even one that arrived as a
        # knowledge_question rather than purchase_intent.
        state = _make_state("How fast can we get a proposal, this is urgent")
        state.detected_intent = "knowledge_question"
        state.lead_score = "hot"
        state.tenant_behavior_config = {
            "lead_handling": {"hot_lead_requires_purchase_intent": False}
        }
        fake_tenant = type("Tenant", (), {"closing_action": "escalate_to_human"})()
        fake_escalation = type("Escalation", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
            patch("app.pipeline.graph.generate_text", return_value="x"),
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "escalate_to_human"

    async def test_hot_lead_requires_purchase_intent_default_keeps_the_gate_narrow(
        self,
    ) -> None:
        # Same message/lead_score as above, default config -- must NOT
        # escalate, proving the widened-gate test above is actually
        # testing the option, not just always-escalating regardless.
        state = _make_state("How fast can we get a proposal, this is urgent")
        state.detected_intent = "knowledge_question"
        state.lead_score = "hot"
        with patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list = AsyncMock(return_value=[])
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "keep_chatting"

    async def test_closing_action_override_takes_precedence_over_tenant_column(self) -> None:
        state = _make_state("I want to order 5 jars right now, how do I pay?")
        state.detected_intent = "purchase_intent"
        state.lead_score = "hot"
        state.tenant_behavior_config = {
            "lead_handling": {"closing_action_override": "book_or_checkout"}
        }
        # Tenant.closing_action says escalate_to_human -- the override must win.
        fake_tenant = type("Tenant", (), {"closing_action": "escalate_to_human"})()
        with (
            patch("app.pipeline.graph.TenantTriggerPhraseRepository") as mock_phrase_repo_cls,
            patch("app.pipeline.graph.TenantRepository") as mock_tenant_repo_cls,
        ):
            mock_phrase_repo_cls.return_value.list = AsyncMock(return_value=[])
            mock_tenant_repo_cls.return_value.get = AsyncMock(return_value=fake_tenant)
            result = await decide_next_step(state, _make_runtime())
        assert result.decision == "book_or_checkout"


class TestCallTools:
    def test_skips_when_intent_does_not_need_grounding(self) -> None:
        for intent in ("small_talk", "other"):
            state = _make_state("hi")
            state.detected_intent = intent
            state.tenant_behavior_config = {
                "tool_calling": {"order_status_lookup_enabled": True}
            }
            with patch("app.pipeline.graph.generate_with_tools") as mock_gen:
                result = call_tools(state)
            mock_gen.assert_not_called()
            assert result.tool_call_results == []

    def test_skips_when_no_tools_enabled(self) -> None:
        # All-defaults TenantBehaviorConfig (tool_calling off, the actual
        # default for every tenant today) -- zero extra Gemini calls, the
        # required byte-identical-at-defaults guarantee.
        state = _make_state("Where's my order #12345?")
        state.detected_intent = "knowledge_question"
        with patch("app.pipeline.graph.generate_with_tools") as mock_gen:
            result = call_tools(state)
        mock_gen.assert_not_called()
        assert result.tool_call_results == []

    def test_populates_tool_call_results_on_a_real_tool_call(self) -> None:
        # Only generate_with_tools is mocked -- the connector itself is
        # real and deterministic, matching this module's own "don't mock
        # the fake data layer" approach.
        state = _make_state("Where's my order #12345?")
        state.detected_intent = "knowledge_question"
        state.tenant_behavior_config = {
            "tool_calling": {"order_status_lookup_enabled": True}
        }
        tool_call = ToolCallRequest(name="order_status_lookup", args={"order_number": "12345"})
        with patch(
            "app.pipeline.graph.generate_with_tools", return_value=(None, [tool_call])
        ):
            result = call_tools(state)
        assert len(result.tool_call_results) == 1
        assert "12345" in result.tool_call_results[0]

    def test_leaves_empty_when_model_calls_no_tool(self) -> None:
        state = _make_state("Where's my order #12345?")
        state.detected_intent = "knowledge_question"
        state.tenant_behavior_config = {
            "tool_calling": {"order_status_lookup_enabled": True}
        }
        with patch(
            "app.pipeline.graph.generate_with_tools", return_value=("no tool needed", [])
        ):
            result = call_tools(state)
        assert result.tool_call_results == []

    def test_ignores_hallucinated_tool_call_without_raising(self) -> None:
        state = _make_state("Where's my order #12345?")
        state.detected_intent = "knowledge_question"
        state.tenant_behavior_config = {
            "tool_calling": {"order_status_lookup_enabled": True}
        }
        with patch(
            "app.pipeline.graph.generate_with_tools",
            return_value=(None, [ToolCallRequest(name="delete_all_orders", args={})]),
        ):
            result = call_tools(state)
        assert result.tool_call_results == []

    def test_only_offers_tools_the_tenant_has_enabled(self) -> None:
        state = _make_state("Where's my order #12345?")
        state.detected_intent = "knowledge_question"
        state.tenant_behavior_config = {
            "tool_calling": {
                "order_status_lookup_enabled": True,
                "inventory_check_enabled": False,
            }
        }
        with patch(
            "app.pipeline.graph.generate_with_tools", return_value=(None, [])
        ) as mock_gen:
            call_tools(state)
        declarations = mock_gen.call_args.args[1]
        assert [d.name for d in declarations] == ["order_status_lookup"]


class TestKeepChatting:
    async def test_sets_draft_text_from_model_response(self) -> None:
        state = _make_state("Do you ship internationally?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["We ship worldwide via DHL."]
        with patch(
            "app.pipeline.graph.generate_text",
            return_value="ANSWERED\nYes, we ship worldwide!",
        ):
            result = await keep_chatting(state, _make_runtime())
        assert result.draft_text == "Yes, we ship worldwide!"

    async def test_folds_tool_call_results_into_the_same_context_block(self) -> None:
        # call_tools (right before this node) populates tool_call_results;
        # keep_chatting must fold it into the same knowledge context block
        # as retrieved_chunks, not build a separate reply path for it.
        state = _make_state("Where's my order and do you ship worldwide?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["We ship worldwide via DHL."]
        state.tool_call_results = ["Order 12345 status: shipped."]
        with patch(
            "app.pipeline.graph.generate_text", return_value="ANSWERED\nx"
        ) as mock_gen:
            await keep_chatting(state, _make_runtime())
        prompt = mock_gen.call_args.args[0]
        assert "We ship worldwide via DHL." in prompt
        assert "Order 12345 status: shipped." in prompt

    async def test_handles_no_retrieved_chunks_without_erroring(self) -> None:
        state = _make_state("Do you ship internationally?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = []
        with patch(
            "app.pipeline.graph.generate_text",
            return_value="ANSWERED\nLet me check on that.",
        ) as mock_gen:
            result = await keep_chatting(state, _make_runtime())
        assert result.draft_text == "Let me check on that."
        prompt = mock_gen.call_args.args[0]
        assert "no matching knowledge found" in prompt

    async def test_grounds_reply_for_information_seeking_intents(self) -> None:
        # knowledge_question/purchase_intent/complaint_or_problem all get
        # the strict "don't guess" grounding instruction + the knowledge
        # block -- there's a real question to ground an answer in.
        for intent in ("knowledge_question", "purchase_intent", "complaint_or_problem"):
            state = _make_state("Do you ship internationally?")
            state.detected_intent = intent
            state.retrieved_chunks = ["We ship worldwide via DHL."]
            with patch(
                "app.pipeline.graph.generate_text", return_value="ANSWERED\nx"
            ) as mock_gen:
                await keep_chatting(state, _make_runtime())
            prompt = mock_gen.call_args.args[0]
            assert "Ground your reply ONLY in the knowledge" in prompt
            assert "We ship worldwide via DHL." in prompt

    async def test_skips_grounding_for_small_talk_and_other(self) -> None:
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
                await keep_chatting(state, _make_runtime())
            prompt = mock_gen.call_args.args[0]
            assert "Ground your reply ONLY in the knowledge" not in prompt
            # The knowledge block itself shouldn't leak into a greeting reply.
            assert "We ship worldwide via DHL." not in prompt

    async def test_small_talk_instruction_steers_away_from_personal_small_talk(self) -> None:
        # Found live (2026-07-29): "reply naturally and conversationally"
        # was loose enough that the model sometimes answered a greeting
        # with personal small talk ("hi, how's your day going?") instead
        # of a business assistant offering help -- reworded to explicitly
        # rule that out.
        state = _make_state("hi")
        state.detected_intent = "small_talk"
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            await keep_chatting(state, _make_runtime())
        prompt = mock_gen.call_args.args[0]
        assert "isn't asking a specific question" in prompt
        assert "not a personal friend" in prompt
        assert "how their day is going" in prompt

    async def test_other_intent_gets_its_own_non_echo_instruction(self) -> None:
        # Found live (2026-07-29): "other" (understand_intent's genuine
        # catch-all, "doesn't fit any of the above") used to share
        # small_talk's instruction, which falsely claims "nothing was
        # actually asked" -- false for something like "where is mahmood?"
        # (a real message, just not a business question/complaint/
        # purchase interest). That false premise produced a confused
        # reply, up to literally echoing the customer's own message back.
        # "other" now gets its own instruction that acknowledges something
        # was said and explicitly rules out parroting it back.
        state = _make_state("where is mahmood?")
        state.detected_intent = "other"
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            await keep_chatting(state, _make_runtime())
        prompt = mock_gen.call_args.args[0]
        assert "isn't asking a specific question" not in prompt
        assert "something WAS actually said" in prompt
        assert "Never repeat or echo the customer's own message" in prompt

    async def test_includes_history_and_continuation_instruction_when_present(self) -> None:
        state = _make_state("What about shipping?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["We ship worldwide via DHL."]
        state.conversation_history = ["Customer: Hi!", "You: Hey there!"]
        with patch(
            "app.pipeline.graph.generate_text", return_value="ANSWERED\nx"
        ) as mock_gen:
            await keep_chatting(state, _make_runtime())
        prompt = mock_gen.call_args.args[0]
        assert "Earlier in this conversation" in prompt
        assert "Hey there!" in prompt
        assert "continuation of an ongoing conversation" in prompt

    async def test_omits_continuation_instruction_for_a_conversations_first_message(
        self,
    ) -> None:
        state = _make_state("hi")
        state.detected_intent = "small_talk"
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            await keep_chatting(state, _make_runtime())
        prompt = mock_gen.call_args.args[0]
        assert "Earlier in this conversation" not in prompt
        assert "continuation of an ongoing conversation" not in prompt

    async def test_grounding_instruction_includes_clarifying_question_branch(self) -> None:
        # docs/ROADMAP.md §3.2 -- an ambiguous knowledge_question ("kırmızı
        # var mı?" with no product named) should be able to get exactly one
        # clarifying question instead of always falling to the "I don't
        # have that information" disclaimer. This only checks the
        # instruction reaches the model; the model's actual judgment call
        # isn't something a unit test can exercise.
        state = _make_state("kırmızı var mı?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["Available colors: blue, green, black."]
        with patch(
            "app.pipeline.graph.generate_text", return_value="CLARIFY\nx"
        ) as mock_gen:
            await keep_chatting(state, _make_runtime())
        prompt = mock_gen.call_args.args[0]
        assert "ask exactly ONE short, natural clarifying question" in prompt
        assert "not an escalation" in prompt

    async def test_clarifying_question_branch_not_offered_for_small_talk(self) -> None:
        # Small talk/other still skip the whole grounding instruction (no
        # question was asked at all), so the clarifying-question branch
        # shouldn't leak in there either.
        state = _make_state("hi")
        state.detected_intent = "small_talk"
        with patch("app.pipeline.graph.generate_text", return_value="x") as mock_gen:
            await keep_chatting(state, _make_runtime())
        prompt = mock_gen.call_args.args[0]
        assert "clarifying question" not in prompt

    async def test_prior_clarifying_question_is_visible_in_history_for_the_followup(
        self,
    ) -> None:
        # The mechanism that keeps this to *exactly* one question: if the
        # model already asked one last turn, it's right there in the
        # history block, so the customer's follow-up reply lands in
        # branch 2/3 of the instruction instead of triggering another ask.
        state = _make_state("kırmızısı")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["Available colors: blue, green, black."]
        state.conversation_history = ["Customer: kırmızı var mı?", "You: neyin kırmızısı?"]
        with patch(
            "app.pipeline.graph.generate_text", return_value="ANSWERED\nx"
        ) as mock_gen:
            await keep_chatting(state, _make_runtime())
        prompt = mock_gen.call_args.args[0]
        assert "neyin kırmızısı?" in prompt

    async def test_not_found_status_creates_a_real_non_blocking_escalation(self) -> None:
        # Found live (2026-07-29): this branch used to just tell the
        # customer "a person will confirm" without ever actually creating
        # an Escalation row or notifying anyone -- a false promise, not
        # just an unhelpful dead end. Now it escalates for real, same
        # non-blocking shape as log_lead_and_notify's book_or_checkout
        # fallback (blocks_pipeline=False -- no interrupt() pause here).
        state = _make_state("What are the business hours?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = []
        fake_escalation = type("Esc", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
            patch(
                "app.pipeline.graph.generate_text",
                side_effect=[
                    "NOT_FOUND\nI don't have that information and a person will confirm.",
                    "We'll double check and get right back to you!",
                ],
            ),
        ):
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            result = await keep_chatting(state, _make_runtime())

        assert result.decision == "escalate_to_human"
        assert result.escalation_logged is True
        assert result.escalation_reason is not None
        # The cover reply (second generate_text call) replaces the raw
        # disclaimer -- the customer never sees the NOT_FOUND-branch text.
        assert result.draft_text == "We'll double check and get right back to you!"
        logged = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged.layer == "knowledge_gap"
        assert logged.blocks_pipeline is False
        assert logged.status == "pending"
        note = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert note.escalation_id == fake_escalation.id
        assert note.audience == "internal"

    async def test_answered_and_clarify_status_do_not_escalate(self) -> None:
        for status, reply in (
            ("ANSWERED", "We ship worldwide via DHL."),
            ("CLARIFY", "Which product did you mean?"),
        ):
            state = _make_state("Do you ship internationally?")
            state.detected_intent = "knowledge_question"
            state.retrieved_chunks = ["We ship worldwide via DHL."]
            with patch(
                "app.pipeline.graph.generate_text", return_value=f"{status}\n{reply}"
            ):
                result = await keep_chatting(state, _make_runtime())
            assert result.draft_text == reply
            assert result.decision is None
            assert result.escalation_reason is None

    async def test_unparseable_status_falls_back_to_raw_text_without_erroring(self) -> None:
        # The model won't always follow the STATUS-line format perfectly --
        # falling back to the raw text (pre-fix behavior) is safer than
        # crashing or silently dropping the reply.
        state = _make_state("Do you ship internationally?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["We ship worldwide via DHL."]
        with patch(
            "app.pipeline.graph.generate_text",
            return_value="Sure, we ship worldwide!",
        ):
            result = await keep_chatting(state, _make_runtime())
        assert result.draft_text == "Sure, we ship worldwide!"
        assert result.decision is None

    async def test_untagged_disclaimer_content_still_escalates(self) -> None:
        # Found live (2026-07-29), real DB evidence, not a hypothetical:
        # the EMAIL channel's own tone guidance ("brief greeting... short
        # sign-off") competes with the STATUS-tag instruction, and the
        # model dropped the tag entirely while still writing the exact
        # pre-fix disclaimer content ("Dear Customer, ... we do not have
        # that information, and a person will confirm ... Best regards,
        # Customer Support") -- silently reverting to the dead end this
        # whole fix was for. _looks_like_not_found_disclaimer is the
        # content-based safety net for exactly this: no tag, but the text
        # still says the disclaimer.
        state = _make_state("which models do you have")
        state.detected_intent = "knowledge_question"
        state.channel_type = "email"
        state.retrieved_chunks = []
        fake_escalation = type("Esc", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
            patch(
                "app.pipeline.graph.generate_text",
                side_effect=[
                    "Dear Customer,\n\nWe do not have that information, and a "
                    "person will confirm the available models for you.\n\n"
                    "Best regards,\nCustomer Support",
                    "Let me check with a colleague and follow up shortly!",
                ],
            ),
        ):
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            result = await keep_chatting(state, _make_runtime())

        assert result.decision == "escalate_to_human"
        assert result.escalation_logged is True
        assert result.draft_text == "Let me check with a colleague and follow up shortly!"
        logged = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged.layer == "knowledge_gap"

    async def test_untagged_answered_text_does_not_falsely_escalate(self) -> None:
        # The content-based fallback must not fire on ordinary untagged
        # replies that don't contain disclaimer language -- covered
        # separately from test_unparseable_status_falls_back... above to
        # make the "no false positive" property explicit in its own right.
        state = _make_state("Do you ship internationally?")
        state.detected_intent = "knowledge_question"
        state.retrieved_chunks = ["We ship worldwide via DHL."]
        with patch(
            "app.pipeline.graph.generate_text",
            return_value="Yes, we ship worldwide via DHL!",
        ):
            result = await keep_chatting(state, _make_runtime())
        assert result.decision is None
        assert result.escalation_reason is None
        assert result.decision is None


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
        # This is the book_or_checkout-fallback catch (the only path that
        # reaches this branch -- decide_next_step's own two escalation
        # branches already set escalation_logged=True, see the test above
        # this one), which never actually pauses the graph -- so
        # blocks_pipeline must be False, or check_pending_escalation
        # (docs/ROADMAP.md §3.1) would wrongly freeze this conversation
        # over what's just a tenant-config nag.
        state = _make_state("Can you guarantee this will definitely cure my condition?")
        state.lead_score = "warm"
        state.decision = "escalate_to_human"
        state.escalation_reason = "book_or_checkout: tenant has no closing_link configured"
        state.draft_text = "Someone will follow up shortly to complete this."
        fake_escalation = type("Escalation", (), {"id": uuid.uuid4()})()
        with (
            patch("app.pipeline.graph.LeadRepository") as mock_lead_repo_cls,
            patch("app.pipeline.graph.EscalationRepository") as mock_escalation_repo_cls,
            patch("app.pipeline.graph.MessageRepository") as mock_message_repo_cls,
        ):
            mock_lead_repo_cls.return_value.add = AsyncMock()
            mock_escalation_repo_cls.return_value.add = AsyncMock(return_value=fake_escalation)
            mock_message_repo_cls.return_value.add = AsyncMock()
            await log_lead_and_notify(state, _make_runtime())

        mock_escalation_repo_cls.return_value.add.assert_called_once()
        logged_escalation = mock_escalation_repo_cls.return_value.add.call_args.args[0]
        assert logged_escalation.reason == state.escalation_reason
        assert logged_escalation.layer == "platform_floor"
        assert logged_escalation.status == "pending"
        assert logged_escalation.blocks_pipeline is False
        # No new generate_text call here -- book_or_checkout already set
        # draft_text earlier in the same run; this just adds the internal
        # note explaining why.
        mock_message_repo_cls.return_value.add.assert_called_once()
        note = mock_message_repo_cls.return_value.add.call_args.args[0]
        assert note.audience == "internal"
        assert note.escalation_id == fake_escalation.id
        assert "closing_link" in note.text

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
