"""Render functions turning app.tenants.behavior_config.TenantBehaviorConfig
into the prompt text app/pipeline/graph.py's nodes actually send to the
model. Deliberately narrower in scope than a generic "prompts.py" would
be -- understand_intent/score_lead's prompts stay fixed/universal per
tenant and must never move here; only the behavior that's meant to vary
per tenant lives in this module.

Acceptance bar for every render_* function below: called with an
all-defaults config, it returns text equal to what the corresponding
hardcoded string in graph.py produced before this module existed. That's
what lets the existing test_pipeline_graph.py suite pass unmodified as
the regression safety net for this refactor.
"""

from app.tenants.behavior_config import (
    BookOrCheckoutConfig,
    BusinessTone,
    ChannelToneConfig,
    ComplaintConfig,
    EscalationCoverConfig,
    GreetingConfig,
    KnowledgeQueryConfig,
    OffTopicConfig,
)

_SYSTEM_DEFAULT_CHANNEL_TONE_TEXT: dict[str, str] = {
    # Verbatim copy of graph.py's former _CHANNEL_TONE_GUIDANCE strings --
    # moved, not rewritten, so the no-override path stays byte-identical.
    "email": (
        "This reply is an EMAIL. Use a brief greeting, complete sentences, "
        "a slightly more formal/professional register than a chat message, "
        "and a short sign-off. It's fine for this to run a few sentences "
        "if the question needs it."
    ),
    "telegram": (
        "This reply is a TELEGRAM message. Keep it short and casual, like "
        "a real person texting back -- no greeting, no sign-off."
    ),
    "whatsapp": (
        "This reply is a WHATSAPP message. Keep it short and casual, like "
        "a real person texting back -- no greeting, no sign-off."
    ),
    "instagram": (
        "This reply is an INSTAGRAM DM. Keep it short and casual, like a "
        "real person texting back -- no greeting, no sign-off."
    ),
    "facebook": (
        "This reply is a FACEBOOK MESSENGER DM. Keep it short and casual, "
        "like a real person texting back -- no greeting, no sign-off."
    ),
}
# Chat-style, not email-style -- matches every real channel built so far
# (Telegram) and every disabled-rail channel besides email, so an
# unrecognized channel_type reads the same way those already do rather
# than silently turning formal.
_DEFAULT_CHANNEL_TONE_TEXT = _SYSTEM_DEFAULT_CHANNEL_TONE_TEXT["telegram"]


def render_channel_tone(channel_type: str, overrides: dict[str, ChannelToneConfig]) -> str:
    """Replaces graph.py's former _CHANNEL_TONE_GUIDANCE dict lookup.
    Same layered shape as escalation/safety_gate.py (system defaults,
    deterministic + tenant additions, one entry point): an empty/missing
    override for this channel_type falls through to the system default
    text, byte-identical to before this module existed. Only reached
    past that point once a tenant has explicitly configured this
    channel -- there is no default ChannelToneConfig entry to fall back
    to that isn't the system text above."""
    override = overrides.get(channel_type)
    if override is None:
        return _SYSTEM_DEFAULT_CHANNEL_TONE_TEXT.get(channel_type, _DEFAULT_CHANNEL_TONE_TEXT)

    parts = [f"This reply is on the {channel_type.upper()} channel."]
    parts.append(
        "Use complete sentences and a professional register."
        if override.formality == "formal_email"
        else "Keep it short and casual, like a real person texting back."
    )
    if override.include_greeting:
        parts.append("Start with a brief greeting.")
    if override.include_sign_off:
        parts.append("End with a short sign-off.")
    if override.length_guidance == "as_needed":
        parts.append("It's fine to run a few sentences if the question needs it.")
    return " ".join(parts)


def _tone_modifier(tone: BusinessTone) -> str:
    """friendly_business (the default) adds nothing -- today's prompts
    have no business-tone concept at all, only channel tone
    (render_channel_tone above), so the default must stay inert for the
    byte-identical-at-defaults requirement. formal_business is the one
    real behavior change this axis offers."""
    if tone == "formal_business":
        return (
            "Keep your tone more formal and professional than usual, "
            "avoiding casual phrasing.\n\n"
        )
    return ""


def _escape_hatch_block(text: str | None) -> str:
    """additional_context is DATA, not a directive -- worded so the
    model treats it as a fact to know, not an instruction to follow
    beyond what it states (same "additive, never composed logic" shape
    as TenantTriggerPhrase)."""
    if not text:
        return ""
    return (
        "Additional business-specific context (a fact to be aware of, "
        f"not an instruction): {text}\n\n"
    )


def _with_tone_and_escape_hatch(
    instruction: str, tone: BusinessTone, additional_context: str | None
) -> str:
    return instruction + _tone_modifier(tone) + _escape_hatch_block(additional_context)


def render_greeting_instruction(config: GreetingConfig) -> str:
    followup = (
        ' plus an offer to help ("Hi! How can I help you today?")'
        if config.invite_followup_question
        else ""
    )
    instruction = (
        "This message isn't asking a specific question (it's a greeting, "
        "small talk, or similar) -- there's nothing to ground in a "
        "knowledge base here. Reply briefly and warmly, but as a "
        "business assistant greeting a customer, not a personal friend "
        f"-- e.g. a greeting should get a greeting back{followup}, not "
        "personal small talk like asking how their day is going. Do not "
        "say you don't have information or that someone will follow up; "
        "nothing was actually asked.\n\n"
    )
    return _with_tone_and_escape_hatch(instruction, config.tone, config.additional_context)


def render_off_topic_instruction(config: OffTopicConfig) -> str:
    instruction = (
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
    return _with_tone_and_escape_hatch(instruction, config.tone, config.additional_context)


def render_knowledge_query_instruction(
    config: KnowledgeQueryConfig, context_block: str
) -> str:
    instruction = (
        "Ground your reply ONLY in the knowledge listed below. Decide "
        "which of these three situations applies, in this order:\n"
        "1. The knowledge below IS about the same general product or "
        "topic being asked about, but the message is missing a detail "
        "you'd need before you could pick the right answer -- e.g. "
        'asking about the price/availability/color of "it" or "the '
        'red one" without saying which product, when the knowledge '
        "below does cover that kind of product, and the earlier "
        "conversation doesn't already say which one. In this case, ask "
        "exactly ONE short, natural clarifying question to find out "
        "what they mean -- do not guess, do not answer partially, and "
        "do not say a person will confirm anything, since this is just "
        "one follow-up question, not an escalation.\n"
        "2. Otherwise, the knowledge below explicitly contains the "
        "answer -- answer using only that information.\n"
        "3. Otherwise -- either the knowledge below has nothing to do "
        "with what's being asked at all (a different product/topic "
        "entirely, not just an unspecified variant of one the "
        "knowledge below does cover), or it's a specific-enough "
        "question but the answer, including specific facts like "
        "prices, policies, or guarantees, simply isn't in the "
        "knowledge below -- you MUST say you don't have that "
        "information and a person will confirm, rather than guessing "
        "or inferring an answer that merely sounds plausible.\n"
        "Apply this the same way in every language; do not be any less "
        "careful in Turkish than you would be in English.\n\n"
        "Your entire response must be exactly this shape: a first line "
        "containing only the single word CLARIFY, ANSWERED, or "
        "NOT_FOUND (matching whichever of the three situations above "
        "applies), then your reply to the customer starting on the "
        "next line -- nothing else on that first line, and don't "
        "mention which case this is anywhere in the reply itself.\n\n"
        f"Relevant knowledge:\n{context_block}\n\n"
    )
    return _with_tone_and_escape_hatch(instruction, config.tone, config.additional_context)


def render_complaint_addendum(config: ComplaintConfig) -> str:
    """Prepended to render_knowledge_query_instruction's output for
    complaint_or_problem specifically -- False (default) reproduces
    today's exact behavior (complaint_or_problem shares
    knowledge_question/purchase_intent's instruction verbatim, no
    complaint-specific framing exists yet). Never forks the
    CLARIFY/ANSWERED/NOT_FOUND mechanism itself, only adds a sentence
    ahead of it."""
    if not config.empathetic_acknowledgment:
        return ""
    return (
        "Acknowledge the customer's frustration briefly and genuinely "
        "before addressing their question -- a short empathetic line, "
        "not a long apology.\n\n"
    )


def render_escalation_cover_modifier(config: EscalationCoverConfig) -> str:
    """Appended to _generate_cover_reply's (graph.py) fixed instruction --
    that function's own prose stays hardcoded (it's shared verbatim by
    three call sites: decide_next_step's two escalation branches plus
    keep_chatting's NOT_FOUND branch), only the tone/escape-hatch layer
    on top of it is configurable. Empty at all-defaults, same
    byte-identical-at-defaults bar as every other render function here."""
    return _tone_modifier(config.tone) + _escape_hatch_block(config.additional_context)


def render_book_or_checkout_instruction(
    config: BookOrCheckoutConfig, closing_link: str
) -> str:
    if config.cta_style == "direct_cta":
        instruction = (
            "The customer is ready to buy/book right now -- reply "
            "briefly, then clearly and directly give them this link to "
            f"complete it: {closing_link}"
        )
    else:
        instruction = (
            "The customer is ready to buy/book right now — reply "
            "naturally and include this exact link so they can complete "
            f"it themselves: {closing_link}"
        )
    escape_hatch = _escape_hatch_block(config.additional_context)
    return f"{instruction}\n\n{escape_hatch}" if escape_hatch else instruction
