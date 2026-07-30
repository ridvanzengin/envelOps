"""Typed, per-tenant AI behavior configuration -- replaces ad-hoc
hardcoded prose/constants in app/pipeline/graph.py (_CHANNEL_TONE_GUIDANCE,
the inline keep_chatting instruction strings) with a versioned schema a
render function (app/pipeline/behavior.py) turns into prompt text.

Two things every model here does deliberately, both load-bearing for
elasticity (add a field/area later without breaking already-stored
per-tenant configs):

- `model_config = ConfigDict(extra="ignore")`, not the default "forbid".
  CLAUDE.md documents a real incident where pydantic-settings' default
  "forbid" broke the whole app at import time over one unmapped env
  var -- "ignore" means a stored config from an older or newer schema
  version deserializes without raising, silently dropping fields this
  version doesn't recognize.
- Every new *value* field uses Literal, not plain str -- a deliberate
  break from this codebase's existing convention (Tenant.closing_action,
  PipelineState.channel_type/detected_intent are all plain str, validity
  enforced by code, not the type system). This schema's whole purpose is
  future UI introspection (dropdown/radio options come directly from
  Literal members), and it's a green-field model so this doesn't risk
  any existing loosely-typed field elsewhere.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_ESCAPE_HATCH_MAX_LENGTH = 500

BusinessTone = Literal["friendly_business", "formal_business"]
ClosingAction = Literal["keep_chatting", "escalate_to_human", "book_or_checkout"]


class BehaviorAreaBase(BaseModel):
    """additional_context is this area's escape hatch: DATA, never
    behavior -- same shape as TenantTriggerPhrase (a plain fact,
    appended verbatim, never composed into new decision logic). Put a
    business fact here ("closed on public holidays"); never a directive
    ("always escalate if X") -- that's the competing-instructions shape
    this whole schema exists to avoid."""

    model_config = ConfigDict(extra="ignore")
    additional_context: str | None = Field(default=None, max_length=_ESCAPE_HATCH_MAX_LENGTH)


class GreetingConfig(BehaviorAreaBase):
    tone: BusinessTone = "friendly_business"
    invite_followup_question: bool = True


class OffTopicConfig(BehaviorAreaBase):
    tone: BusinessTone = "friendly_business"


class KnowledgeQueryConfig(BehaviorAreaBase):
    tone: BusinessTone = "friendly_business"
    # cosine_distance ceiling (0=identical .. ~2=opposite, pgvector's
    # scale). None = no filtering, reproducing search_similar's exact
    # prior behavior (always top-K regardless of relevance) -- inert
    # until a tenant deliberately tightens it.
    not_found_max_distance: float | None = Field(default=None, ge=0.0, le=2.0)


class ComplaintConfig(BehaviorAreaBase):
    # False reproduces today's exact behavior: complaint_or_problem
    # shares knowledge_question/purchase_intent's grounding instruction
    # verbatim today (_INTENTS_NEEDING_GROUNDING). True layers ONE
    # additive empathy sentence onto that same instruction -- never
    # forks the CLARIFY/ANSWERED/NOT_FOUND mechanism itself.
    empathetic_acknowledgment: bool = False


class LeadHandlingConfig(BehaviorAreaBase):
    # None = "read Tenant.closing_action/closing_link exactly as today"
    # -- those columns stay the source of truth this pass; this is a
    # dormant, opt-in override seam, not a live migration.
    closing_action_override: ClosingAction | None = None
    # Reproduces decide_next_step's exact gate (lead_score == "hot" and
    # detected_intent == "purchase_intent"). False widens it to ANY hot
    # lead regardless of intent label -- real, deterministic routing.
    hot_lead_requires_purchase_intent: bool = True


class EscalationCoverConfig(BehaviorAreaBase):
    """Governs ONLY _generate_cover_reply's prose (shared by
    decide_next_step's two escalation sites + keep_chatting's NOT_FOUND
    branch) -- never whether/why an escalation fires. That stays fully
    owned by escalation/safety_gate.py's deterministic check and
    decide_next_step's routing, untouched by this feature."""

    tone: BusinessTone = "friendly_business"


class BookOrCheckoutConfig(BehaviorAreaBase):
    cta_style: Literal["natural_mention", "direct_cta"] = "natural_mention"


class ChannelToneConfig(BaseModel):
    """Per-channel_type ("platform," in this project's own UI vocabulary)
    override. Not a BehaviorAreaBase subclass -- a structural axis
    (per-channel register), not a conversational "behavior area"; a
    cross-cutting note belongs in TenantBehaviorConfig.general_context
    instead of a per-channel escape hatch."""

    model_config = ConfigDict(extra="ignore")
    formality: Literal["casual_chat", "formal_email"] = "casual_chat"
    include_greeting: bool = False
    include_sign_off: bool = False
    length_guidance: Literal["brief", "as_needed"] = "brief"


class TenantBehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = 1

    greeting: GreetingConfig = Field(default_factory=GreetingConfig)
    off_topic: OffTopicConfig = Field(default_factory=OffTopicConfig)
    knowledge_query: KnowledgeQueryConfig = Field(default_factory=KnowledgeQueryConfig)
    complaint: ComplaintConfig = Field(default_factory=ComplaintConfig)
    lead_handling: LeadHandlingConfig = Field(default_factory=LeadHandlingConfig)
    escalation_cover: EscalationCoverConfig = Field(default_factory=EscalationCoverConfig)
    book_or_checkout: BookOrCheckoutConfig = Field(default_factory=BookOrCheckoutConfig)

    # Deliberately plain `str` keys, NOT Literal[<channel names>] --
    # Pydantic validates dict *keys* against a Literal regardless of
    # extra="ignore" (that setting only governs extra model *fields*),
    # so a Literal-keyed dict referencing a channel_type this version
    # doesn't recognize (removed, renamed, or just not added yet) would
    # raise on load instead of degrading gracefully. render_channel_tone
    # (app/pipeline/behavior.py) falls through to the system default on
    # a miss, same as _CHANNEL_TONE_GUIDANCE.get(..., _DEFAULT) does today.
    channel_overrides: dict[str, ChannelToneConfig] = Field(default_factory=dict)

    general_context: str | None = Field(default=None, max_length=_ESCAPE_HATCH_MAX_LENGTH)


def load_tenant_behavior_config(raw: dict[str, Any] | None) -> TenantBehaviorConfig:
    """Single call site every pipeline node uses to get the typed view
    of Tenant.behavior_config's raw dict."""
    return TenantBehaviorConfig.model_validate(raw or {})
