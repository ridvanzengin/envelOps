from app.pipeline.behavior import (
    render_book_or_checkout_instruction,
    render_channel_tone,
    render_complaint_addendum,
    render_escalation_cover_modifier,
    render_greeting_instruction,
    render_knowledge_query_instruction,
    render_off_topic_instruction,
)
from app.tenants.behavior_config import (
    BookOrCheckoutConfig,
    ChannelToneConfig,
    ComplaintConfig,
    EscalationCoverConfig,
    GreetingConfig,
    KnowledgeQueryConfig,
    OffTopicConfig,
)

# Every render_* function's all-defaults output must equal what graph.py's
# hardcoded strings produced before this module existed -- that's what
# lets test_pipeline_graph.py's existing suite pass unmodified as the
# regression net for this refactor. These literals are the pre-refactor
# strings, copied here as the acceptance bar, not re-derived from the
# render functions themselves.
_ORIGINAL_GREETING = (
    "This message isn't asking a specific question (it's a greeting, "
    "small talk, or similar) -- there's nothing to ground in a "
    "knowledge base here. Reply briefly and warmly, but as a "
    "business assistant greeting a customer, not a personal friend "
    "-- e.g. a greeting should get a greeting back plus an offer "
    'to help ("Hi! How can I help you today?"), not personal '
    "small talk like asking how their day is going. Do not say "
    "you don't have information or that someone will follow up; "
    "nothing was actually asked.\n\n"
)

_ORIGINAL_OFF_TOPIC = (
    "This message doesn't fit a specific business question, "
    "complaint, or purchase interest -- it may be off-topic, "
    "unclear, or unrelated to what this business offers, but "
    "something WAS actually said. Acknowledge that briefly and "
    "naturally, without pretending nothing was asked, then "
    "redirect to how you can help with this business specifically "
    '(e.g. "I\'m not sure I can help with that, but happy to '
    'answer anything about [what this business does]!"). Never '
    "repeat or echo the customer's own message back to them as "
    "your reply, and never guess or invent an answer to something "
    "you don't actually know.\n\n"
)

_ORIGINAL_EMAIL_TONE = (
    "This reply is an EMAIL. Use a brief greeting, complete sentences, "
    "a slightly more formal/professional register than a chat message, "
    "and a short sign-off. It's fine for this to run a few sentences "
    "if the question needs it."
)

_ORIGINAL_TELEGRAM_TONE = (
    "This reply is a TELEGRAM message. Keep it short and casual, like "
    "a real person texting back -- no greeting, no sign-off."
)

_ORIGINAL_NATURAL_CTA = (
    "The customer is ready to buy/book right now — reply naturally and "
    "include this exact link so they can complete it themselves: "
    "https://pay.example.com/x"
)


class TestRenderGreetingInstruction:
    def test_defaults_match_original_hardcoded_text(self) -> None:
        assert render_greeting_instruction(GreetingConfig()) == _ORIGINAL_GREETING

    def test_formal_tone_adds_a_modifier_without_changing_the_base_instruction(self) -> None:
        result = render_greeting_instruction(GreetingConfig(tone="formal_business"))
        assert _ORIGINAL_GREETING in result
        assert "more formal" in result

    def test_invite_followup_question_false_drops_the_offer_to_help_clause(self) -> None:
        result = render_greeting_instruction(GreetingConfig(invite_followup_question=False))
        assert "offer to help" not in result
        assert "a greeting should get a greeting back, not personal small talk" in result

    def test_additional_context_is_appended_as_data_not_instruction(self) -> None:
        result = render_greeting_instruction(
            GreetingConfig(additional_context="Closed on public holidays.")
        )
        assert "Closed on public holidays." in result
        assert "not an instruction" in result


class TestRenderOffTopicInstruction:
    def test_defaults_match_original_hardcoded_text(self) -> None:
        assert render_off_topic_instruction(OffTopicConfig()) == _ORIGINAL_OFF_TOPIC


class TestRenderKnowledgeQueryInstruction:
    def test_defaults_match_original_hardcoded_text(self) -> None:
        result = render_knowledge_query_instruction(KnowledgeQueryConfig(), "SOME CONTEXT")
        assert "Ground your reply ONLY in the knowledge listed below" in result
        assert "Relevant knowledge:\nSOME CONTEXT\n\n" in result
        # No tone modifier / escape hatch text leaks in at defaults.
        assert "more formal" not in result
        assert "not an instruction" not in result

    def test_formal_tone_and_escape_hatch_are_both_appended(self) -> None:
        config = KnowledgeQueryConfig(
            tone="formal_business", additional_context="We are cash-only."
        )
        result = render_knowledge_query_instruction(config, "ctx")
        assert "more formal" in result
        assert "We are cash-only." in result

    def test_covers_action_requests_not_just_questions(self) -> None:
        # docs/ROADMAP.md calibration finding: an order-modify/cancel
        # REQUEST needs the same grounding treatment as an information
        # QUESTION, not a free pass to invent an answer just because it's
        # phrased as "can you do X" rather than "do you know X".
        result = render_knowledge_query_instruction(KnowledgeQueryConfig(), "ctx")
        assert "requests to DO something" in result
        assert "cancel" in result

    def test_forbids_inventing_unstated_specifics(self) -> None:
        # docs/ROADMAP.md calibration finding: the model fabricated an
        # ungrounded "email support@shop.com" workflow instead of
        # escalating when the knowledge base didn't cover an order-modify
        # request. The prior wording ("guessing or inferring an answer
        # that merely sounds plausible") wasn't explicit enough to stop
        # this in practice.
        result = render_knowledge_query_instruction(KnowledgeQueryConfig(), "ctx")
        assert "Never invent a next step, workflow, contact email" in result


class TestRenderComplaintAddendum:
    def test_default_is_empty(self) -> None:
        assert render_complaint_addendum(ComplaintConfig()) == ""

    def test_enabled_adds_an_empathy_line(self) -> None:
        result = render_complaint_addendum(ComplaintConfig(empathetic_acknowledgment=True))
        assert result != ""
        assert "frustration" in result


class TestRenderEscalationCoverModifier:
    def test_default_is_empty(self) -> None:
        assert render_escalation_cover_modifier(EscalationCoverConfig()) == ""

    def test_formal_tone_and_context_both_render(self) -> None:
        config = EscalationCoverConfig(
            tone="formal_business", additional_context="VIP client."
        )
        result = render_escalation_cover_modifier(config)
        assert "more formal" in result
        assert "VIP client." in result


class TestRenderChannelTone:
    def test_email_default_matches_original_text(self) -> None:
        assert render_channel_tone("email", {}) == _ORIGINAL_EMAIL_TONE

    def test_telegram_default_matches_original_text(self) -> None:
        assert render_channel_tone("telegram", {}) == _ORIGINAL_TELEGRAM_TONE

    def test_unrecognized_channel_falls_back_to_telegram_style(self) -> None:
        assert render_channel_tone("some_future_channel", {}) == _ORIGINAL_TELEGRAM_TONE

    def test_override_produces_materially_different_text(self) -> None:
        override = ChannelToneConfig(
            formality="formal_email",
            include_greeting=True,
            include_sign_off=True,
            length_guidance="as_needed",
        )
        result = render_channel_tone("telegram", {"telegram": override})
        assert result != _ORIGINAL_TELEGRAM_TONE
        assert "professional register" in result
        assert "brief greeting" in result
        assert "short sign-off" in result
        assert "fine to run a few sentences" in result

    def test_override_for_a_different_channel_does_not_affect_this_one(self) -> None:
        override = ChannelToneConfig(formality="formal_email")
        result = render_channel_tone("telegram", {"email": override})
        assert result == _ORIGINAL_TELEGRAM_TONE


class TestRenderBookOrCheckoutInstruction:
    def test_natural_mention_default_matches_original_text(self) -> None:
        result = render_book_or_checkout_instruction(
            BookOrCheckoutConfig(), "https://pay.example.com/x"
        )
        assert result == _ORIGINAL_NATURAL_CTA

    def test_direct_cta_produces_different_text_but_keeps_the_link(self) -> None:
        result = render_book_or_checkout_instruction(
            BookOrCheckoutConfig(cta_style="direct_cta"), "https://pay.example.com/x"
        )
        assert result != _ORIGINAL_NATURAL_CTA
        assert "https://pay.example.com/x" in result

    def test_additional_context_is_appended_with_separation(self) -> None:
        config = BookOrCheckoutConfig(additional_context="Local pickup also available.")
        result = render_book_or_checkout_instruction(config, "https://pay.example.com/x")
        assert "Local pickup also available." in result
        assert result.startswith(_ORIGINAL_NATURAL_CTA)
