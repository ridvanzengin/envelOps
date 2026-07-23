"""Layer 1 platform-enforced safety floor (docs/REQUIREMENTS.md §6):
mandatory escalation on contraindication language, symptom/complaint
language, or outcome-guarantee requests. Must be a separate, narrower check
from the reply-generation model, and its result is a hard gate.

The patterns below are a Phase 1 starting point, not a validated safety
classifier — they're deterministic and auditable (every trigger names the
exact pattern(s) that fired, for the escalation log), but a plain regex list
will miss plenty of real phrasing in either language. Treat expanding/
replacing this with a proper check as required before relying on it for
real health-related tenants, not as a nice-to-have.

Turkish and English patterns are both checked on every message (docs/
ARCHITECTURE.md §7 — the pipeline detects language, it doesn't ask, and the
safety floor can't assume the reply-generation language guess is right by
the time this runs). Known limitation: Python's IGNORECASE case-folds "İ"/"I"
the ASCII way, not the Turkish way, so all-caps Turkish input with dotted/
dotless I is the one case that can slip past a pattern that would otherwise
match — patterns below are written to avoid relying on I-casing where
possible, but this isn't fully solved.

Outcome-guarantee detection requires a certainty word ("guarantee",
"garanti", "definitely", "kesinlikle"...) AND an efficacy/outcome word
("work", "cure", "çalışır", "iyileşir"...) in the same message, not either
alone — a bare "guarantee"/"garanti" match is far too common in ordinary
e-commerce copy (shipping guarantees, product warranties, "ürün garantisi")
to use as a standalone trigger.
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
        # English
        r"\binteract(?:s|ion)?\s+with\s+(?:my\s+)?(?:medication|drug|pill)",
        r"\bcontraindicat\w*",
        r"\bcan\s+i\s+(?:take|use|combine)\b.{0,40}\b(?:with|and)\b.{0,40}\b(?:medication|drug|pill)\b",
        r"\ballerg(?:y|ic)\b",
        # Turkish
        r"\bilaç\w*\s+ile\s+(?:etkileş\w*|birlikte\s+kullan\w*)",
        r"\bilacım\w*\s+ile\s+(?:birlikte\s+)?kullan\w*",
        r"\bkontrendik\w*",
        r"\balerjim\s+var\b",
        r"\balerjik\w*\b",
    ]
)

_SYMPTOM_PATTERNS = _compile_all(
    [
        # English
        r"\bit\s+hurts\b",
        r"\bin\s+(?:so\s+much\s+)?pain\b",
        r"\bbleed(?:ing)?\b",
        r"\bswoll(?:en|ing)\b",
        r"\brash\b",
        r"\bside\s+effects?\b",
        r"\b(?:bad|allergic)\s+reaction\b",
        r"\binfect(?:ed|ion)\b",
        # Turkish — note: "şiş" alone/with these suffixes only, NOT \bşiş\w*\b,
        # which would also match "şişe" (bottle) and "şişeler"/"şişeyi" etc.,
        # all extremely common words for a business selling honey in bottles.
        r"\bacı\w*\s+(?:veriyor|yapıyor)\b",
        r"\bağrı\w*\s+var\b",
        r"\bkan(?:ıyor|\s+(?:geliyor|akıyor))\b",
        r"\bşiş(?:lik|miş|kin|ti|ip|iyor)?\b",
        r"\bdöküntü\w*\b",
        r"\byan\s+etki\w*\b",
        r"\balerjik\s+reaksiyon\w*\b",
        r"\benfekt\w*\b",
    ]
)

_CERTAINTY_CUES = _compile_all(
    [
        # English
        r"\bguarantee[sd]?\b",
        r"\b100\s*%\s*(?:sure|certain|guaranteed)\b",
        r"\bdefinitely\b",
        r"\bpromise\b",
        # Turkish
        r"\bgaranti\w*\b",
        r"\b(?:yüzde\s*100|%\s*100)\s+(?:emin|garanti)\w*\b",
        r"\bkesin(?:likle)?\b",
        r"\bsöz\s+ver\w*\b",
    ]
)

_EFFICACY_CUES = _compile_all(
    [
        # English
        r"\bwork(?:s|ed|ing)?\b",
        r"\bcure[sd]?\b",
        r"\bheal(?:s|ed|ing)?\b",
        r"\bfix(?:es|ed|ing)?\b",
        r"\bhelp\w*\b",
        # Turkish
        r"\bçalış\w*\b",
        r"\bişe\s+yara\w*\b",
        r"\biyileş\w*\b",
        r"\btedavi\w*\b",
        r"\bgeçer\s+mi\b",  # e.g. "ağrım geçer mi" — will my pain go away
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
    business owner types a phrase ("mad honey" / "deli bal"), not a pattern.
    `phrases` comes from `TenantTriggerPhraseRepository`; this function has
    no DB dependency itself, same as `check_platform_safety_floor`."""
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
