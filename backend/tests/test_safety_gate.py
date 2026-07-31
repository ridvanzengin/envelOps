import unittest

from app.escalation.safety_gate import (
    check_platform_safety_floor,
    check_safety_floor,
    check_tenant_trigger_phrases,
)


class SafetyFloorEnglishTests(unittest.TestCase):
    def test_no_trigger_on_ordinary_question(self) -> None:
        self.assertIsNone(check_platform_safety_floor("What are your opening hours?"))

    def test_no_trigger_on_pricing_question(self) -> None:
        self.assertIsNone(check_platform_safety_floor("How much does the consultation cost?"))

    def test_no_false_positive_on_shipping_guarantee(self) -> None:
        # "guarantee" alone is ordinary e-commerce language (shipping,
        # warranty) — must NOT trigger without an efficacy/outcome word too.
        self.assertIsNone(
            check_platform_safety_floor("Do you guarantee delivery within 3 days?")
        )

    def test_triggers_on_contraindication_language(self) -> None:
        trigger = check_platform_safety_floor(
            "Can I take this with my blood pressure medication?"
        )
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.layer, "platform_floor")

    def test_triggers_on_symptom_language(self) -> None:
        trigger = check_platform_safety_floor("The area is swollen and it hurts a lot")
        self.assertIsNotNone(trigger)

    def test_triggers_on_outcome_guarantee_request(self) -> None:
        trigger = check_platform_safety_floor(
            "Can you guarantee this will definitely work for me?"
        )
        self.assertIsNotNone(trigger)

    def test_triggers_on_risk_absence_guarantee_request(self) -> None:
        # docs/ROADMAP.md §5.1: found live via a health-tourism tenant --
        # the original efficacy list only covered functional-outcome
        # words ("cures", "works"), missing risk-absence claims entirely.
        trigger = check_platform_safety_floor(
            "Can you guarantee this procedure has zero risk of complications?"
        )
        self.assertIsNotNone(trigger)
        self.assertIn("outcome-guarantee", trigger.reason)

    def test_triggers_on_safety_guarantee_request(self) -> None:
        trigger = check_platform_safety_floor(
            "Do you promise this treatment is completely safe?"
        )
        self.assertIsNotNone(trigger)

    def test_no_false_positive_on_bare_risk_or_safety_language(self) -> None:
        # "risk"/"safe" alone, with no certainty word, must not trigger --
        # same AND-not-OR requirement as the original efficacy cues.
        self.assertIsNone(
            check_platform_safety_floor("Is there any risk my package gets lost?")
        )
        self.assertIsNone(
            check_platform_safety_floor("Is it safe to leave the package at my door?")
        )

    def test_reason_names_the_category(self) -> None:
        trigger = check_platform_safety_floor("I'm having an allergic reaction")
        assert trigger is not None
        self.assertIn("contraindication", trigger.reason)


class TenantTriggerPhraseTests(unittest.TestCase):
    def test_no_trigger_when_no_phrases_configured(self) -> None:
        self.assertIsNone(check_tenant_trigger_phrases("mad honey is dangerous", []))

    def test_no_trigger_when_phrase_absent(self) -> None:
        self.assertIsNone(
            check_tenant_trigger_phrases("just a regular order question", ["mad honey"])
        )

    def test_triggers_on_case_insensitive_substring_match(self) -> None:
        trigger = check_tenant_trigger_phrases(
            "Is this Mad Honey? I heard it's intoxicating", ["mad honey"]
        )
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.layer, "platform_floor")
        self.assertIn("mad honey", trigger.reason)

    def test_blank_phrases_are_ignored(self) -> None:
        self.assertIsNone(check_tenant_trigger_phrases("anything at all", ["   ", ""]))


class CombinedSafetyFloorTests(unittest.TestCase):
    def test_system_default_fires_without_tenant_phrases(self) -> None:
        trigger = check_safety_floor("I'm having an allergic reaction", [])
        self.assertIsNotNone(trigger)

    def test_tenant_phrase_fires_when_system_defaults_dont(self) -> None:
        trigger = check_safety_floor("do you sell mad honey?", ["mad honey"])
        self.assertIsNotNone(trigger)

    def test_no_trigger_when_neither_fires(self) -> None:
        self.assertIsNone(check_safety_floor("what flavors do you have?", ["mad honey"]))


if __name__ == "__main__":
    unittest.main()
