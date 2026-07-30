import pytest
from pydantic import ValidationError

from app.tenants.behavior_config import (
    ChannelToneConfig,
    TenantBehaviorConfig,
    load_tenant_behavior_config,
)


class TestDefaults:
    def test_all_defaults_reproduce_todays_behavior(self) -> None:
        config = TenantBehaviorConfig()
        assert config.schema_version == 1
        assert config.greeting.tone == "friendly_business"
        assert config.greeting.invite_followup_question is True
        assert config.knowledge_query.not_found_max_distance is None
        assert config.complaint.empathetic_acknowledgment is False
        assert config.lead_handling.closing_action_override is None
        assert config.lead_handling.hot_lead_requires_purchase_intent is True
        assert config.book_or_checkout.cta_style == "natural_mention"
        assert config.channel_overrides == {}
        assert config.general_context is None

    def test_load_tenant_behavior_config_none_and_empty_dict_both_give_defaults(self) -> None:
        assert load_tenant_behavior_config(None) == TenantBehaviorConfig()
        assert load_tenant_behavior_config({}) == TenantBehaviorConfig()


class TestForwardCompatibility:
    """Elasticity is the whole point of this schema -- a stored config
    from an older or newer schema version must deserialize without
    raising, per extra="ignore" on every model here (not the
    pydantic-settings default "forbid" that once broke the app at
    import time over one unmapped env var, per CLAUDE.md)."""

    def test_unrecognized_top_level_field_does_not_raise(self) -> None:
        config = load_tenant_behavior_config({"a_future_field_this_version_does_not_know": 1})
        assert config == TenantBehaviorConfig()

    def test_unrecognized_nested_field_does_not_raise(self) -> None:
        config = load_tenant_behavior_config(
            {"knowledge_query": {"not_found_max_distance": 0.5, "a_future_field": "z"}}
        )
        assert config.knowledge_query.not_found_max_distance == 0.5

    def test_old_blob_missing_a_newer_field_still_gets_its_default(self) -> None:
        # Simulates a config stored before invite_followup_question existed.
        config = load_tenant_behavior_config({"greeting": {"tone": "formal_business"}})
        assert config.greeting.tone == "formal_business"
        assert config.greeting.invite_followup_question is True

    def test_unrecognized_channel_override_key_does_not_raise(self) -> None:
        # The one deliberate exception to Literal-everywhere: channel_overrides
        # keys stay plain str specifically so an unrecognized channel_type
        # (removed, renamed, or just not added to this deployment yet)
        # degrades gracefully instead of raising.
        config = load_tenant_behavior_config(
            {"channel_overrides": {"some_future_channel": {"formality": "formal_email"}}}
        )
        assert "some_future_channel" in config.channel_overrides
        assert config.channel_overrides["some_future_channel"].formality == "formal_email"


class TestBounds:
    def test_not_found_max_distance_out_of_bounds_raises(self) -> None:
        with pytest.raises(ValidationError):
            load_tenant_behavior_config({"knowledge_query": {"not_found_max_distance": -1}})
        with pytest.raises(ValidationError):
            load_tenant_behavior_config({"knowledge_query": {"not_found_max_distance": 3}})

    def test_not_found_max_distance_in_bounds_is_accepted(self) -> None:
        low = load_tenant_behavior_config({"knowledge_query": {"not_found_max_distance": 0}})
        assert low.knowledge_query.not_found_max_distance == 0
        high = load_tenant_behavior_config({"knowledge_query": {"not_found_max_distance": 2}})
        assert high.knowledge_query.not_found_max_distance == 2

    def test_additional_context_past_max_length_raises(self) -> None:
        with pytest.raises(ValidationError):
            load_tenant_behavior_config({"greeting": {"additional_context": "x" * 501}})

    def test_additional_context_at_max_length_is_accepted(self) -> None:
        config = load_tenant_behavior_config({"greeting": {"additional_context": "x" * 500}})
        assert config.greeting.additional_context == "x" * 500

    def test_invalid_literal_value_raises(self) -> None:
        with pytest.raises(ValidationError):
            load_tenant_behavior_config({"greeting": {"tone": "sarcastic"}})


class TestChannelToneConfig:
    def test_defaults_reproduce_the_chat_style_default(self) -> None:
        config = ChannelToneConfig()
        assert config.formality == "casual_chat"
        assert config.include_greeting is False
        assert config.include_sign_off is False
        assert config.length_guidance == "brief"
