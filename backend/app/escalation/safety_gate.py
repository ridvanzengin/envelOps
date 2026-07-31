"""Layer 1 platform-enforced safety floor (docs/REQUIREMENTS.md §6):
mandatory escalation on contraindication language, symptom/complaint
language, or outcome-guarantee requests. Must be a separate, narrower check
from the reply-generation model, and its result is a hard gate.

The patterns below are a Phase 1 starting point, not a validated safety
classifier — they're deterministic and auditable (every trigger names the
exact pattern(s) that fired, for the escalation log), but a plain regex list
will miss plenty of real phrasing. Treat expanding/replacing this with a
proper check as required before relying on it for real health-related
tenants, not as a nice-to-have.

English only (2026-07-31) — Turkish pattern coverage was cut alongside the
rest of the pipeline's Turkish/bilingual support (CLAUDE.md, REQUIREMENTS
§11); this project is English-only now, no reply-language detection to stay
in sync with.

Outcome-guarantee detection requires a certainty word ("guarantee",
"definitely"...) AND an efficacy/outcome word ("work", "cure"...) in the
same message, not either alone — a bare "guarantee" match is far too common
in ordinary e-commerce copy (shipping guarantees, product warranties) to use
as a standalone trigger.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyTrigger:
    layer: str
    reason: str


def _compile_all(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_CONTRAINDICATION_PATTERNS = _compile_all(
    [
        r"\binteract(?:s|ion)?\s+with\s+(?:my\s+)?(?:medication|drug|pill)",
        r"\bcontraindicat\w*",
        r"\bcan\s+i\s+(?:take|use|combine)\b.{0,40}\b(?:with|and)\b.{0,40}\b(?:medication|drug|pill)\b",
        r"\ballerg(?:y|ic)\b",
    ]
)

_SYMPTOM_PATTERNS = _compile_all(
    [
        r"\bit\s+hurts\b",
        r"\bin\s+(?:so\s+much\s+)?pain\b",
        r"\bbleed(?:ing)?\b",
        r"\bswoll(?:en|ing)\b",
        r"\brash\b",
        r"\bside\s+effects?\b",
        r"\b(?:bad|allergic)\s+reaction\b",
        r"\binfect(?:ed|ion)\b",
    ]
)

_CERTAINTY_CUES = _compile_all(
    [
        r"\bguarantee[sd]?\b",
        r"\b100\s*%\s*(?:sure|certain|guaranteed)\b",
        r"\bdefinitely\b",
        r"\bpromise\b",
    ]
)

_EFFICACY_CUES = _compile_all(
    [
        r"\bwork(?:s|ed|ing)?\b",
        r"\bcure[sd]?\b",
        r"\bheal(?:s|ed|ing)?\b",
        r"\bfix(?:es|ed|ing)?\b",
        r"\bhelp\w*\b",
    ]
)


def _first_match(patterns: list[re.Pattern[str]], text: str) -> re.Pattern[str] | None:
    for pattern in patterns:
        if pattern.search(text):
            return pattern
    return None


def check_platform_safety_floor(text: str) -> SafetyTrigger | None:
    for category, patterns in (
        ("contraindication language", _CONTRAINDICATION_PATTERNS),
        ("symptom/complaint language", _SYMPTOM_PATTERNS),
    ):
        match = _first_match(patterns, text)
        if match is not None:
            return SafetyTrigger(
                layer="platform_floor",
                reason=f"{category} (matched {match.pattern!r})",
            )

    certainty_match = _first_match(_CERTAINTY_CUES, text)
    efficacy_match = _first_match(_EFFICACY_CUES, text)
    if certainty_match is not None and efficacy_match is not None:
        return SafetyTrigger(
            layer="platform_floor",
            reason=(
                "outcome-guarantee request "
                f"(certainty {certainty_match.pattern!r} + "
                f"efficacy {efficacy_match.pattern!r})"
            ),
        )
    return None


def check_tenant_trigger_phrases(text: str, phrases: list[str]) -> SafetyTrigger | None:
    """Tenant additions to Layer 1 (docs/REQUIREMENTS.md §6) — additive
    only, plain case-insensitive substring match, not regex, since a
    business owner types a phrase ("mad honey"), not a pattern. `phrases`
    comes from `TenantTriggerPhraseRepository`; this function has no DB
    dependency itself, same as `check_platform_safety_floor`."""
    lowered = text.lower()
    for phrase in phrases:
        stripped = phrase.strip()
        if stripped and stripped.lower() in lowered:
            return SafetyTrigger(
                layer="platform_floor",
                reason=f"tenant-defined trigger phrase (matched {stripped!r})",
            )
    return None


def check_safety_floor(text: str, tenant_phrases: list[str]) -> SafetyTrigger | None:
    """System defaults first, then tenant additions — either firing is the
    same hard gate (REQUIREMENTS §6). This is what pipeline nodes should
    call; the two functions above stay separate mainly so each is testable
    on its own."""
    return check_platform_safety_floor(text) or check_tenant_trigger_phrases(
        text, tenant_phrases
    )
