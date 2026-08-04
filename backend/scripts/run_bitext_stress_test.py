"""Runs a sample of real customer-support messages from the public Bitext
customer-support dataset (docs/ROADMAP.md's DM-dataset research) through
the real pipeline against Meadow & Jar Honey Co's knowledge base, to
stress-test intent classification and knowledge grounding with phrasing
the hand-written synthetic scripts don't happen to cover.

Prerequisites:
- `docker compose up` (or backend + db running) with a real
  `ENVELOPS_GEMINI_API_KEY`
- The dataset CSV downloaded to `backend/data/bitext_customer_support_27k.csv`
  (not checked in -- fetch from
  https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset)
- Meadow & Jar Honey Co already seeded (scripts/seed_showcase_tenants.py)
  with its 26-entry FAQ knowledge base -- this script logs in through the
  real POST /auth/login with that seed script's own known DEMO_PASSWORD,
  not any no-password bypass, so it has no dependency on
  ENVELOPS_DEMO_MODE_ENABLED (deliberately: that flag also makes Test
  Console stop persisting messages, which would silently defeat this
  script's whole point -- see its own docstring below)

Only 14 of Bitext's 27 intents are used -- ORDER/CANCEL/SHIPPING/DELIVERY/
REFUND/PAYMENT, the categories that actually match what a small DM seller's
knowledge base would cover. The other ~13 (ACCOUNT/SUBSCRIPTION/INVOICE/
CONTACT/FEEDBACK -- account logins, invoice downloads, newsletter
management) assume a self-service platform account system this business
doesn't have, so they're not a meaningful "should this be answered"
test here.

Sends each message through the real Test Console API (not a direct
run_pipeline call) so conversations show up inspectable in the UI
exactly like every other Test Console session, tagged with a
"bitext-stress-" external_contact_id prefix for easy identification --
same is_test=True + visible-in-rail convention already used by every
other test conversation, not a new mechanism.

Run directly (needs the API reachable at localhost:8000):

    cd backend && source .venv/bin/activate && python3 -m
    scripts.run_bitext_stress_test
"""

import csv
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"
OWNER_EMAIL = "owner@meadow-jar-honey.demo"
# scripts/seed_showcase_tenants.py/seed_calibration_tenant.py's own
# constant, duplicated here rather than imported -- this script predates
# neither depending on the other, and a shared constants module would be
# more machinery than three files agreeing on one literal string needs.
DEMO_PASSWORD = "EnvelOpsDemo!1"
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "bitext_customer_support_27k.csv"

# ORDER, CANCEL, SHIPPING, DELIVERY, REFUND, PAYMENT categories only --
# the subset that maps onto a small e-commerce seller's actual knowledge
# base, per the session's own scoping discussion.
RELEVANT_INTENTS = [
    "place_order",
    "change_order",
    "track_order",
    "cancel_order",
    "check_cancellation_fee",
    "set_up_shipping_address",
    "change_shipping_address",
    "delivery_period",
    "delivery_options",
    "get_refund",
    "track_refund",
    "check_refund_policy",
    "payment_issue",
    "check_payment_methods",
]

SAMPLES_PER_INTENT = 2
DELAY_BETWEEN_MESSAGES_SECONDS = 20  # same free-tier headroom reasoning as
# run_synthetic_conversations.py -- up to a few generate_text calls per
# message, Gemini free tier caps at 15 req/min.

PLACEHOLDER_RE = re.compile(r"\{\{Order Number\}\}")


@dataclass
class SampledMessage:
    intent: str
    category: str
    text: str


def load_samples() -> list[SampledMessage]:
    if not CSV_PATH.exists():
        raise SystemExit(
            f"{CSV_PATH} not found -- download it first (see this script's docstring)"
        )

    by_intent: dict[str, list[tuple[str, str]]] = {}
    with CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            if row["intent"] in RELEVANT_INTENTS:
                entry = (row["category"], row["instruction"])
                by_intent.setdefault(row["intent"], []).append(entry)

    rng = random.Random(0)  # reproducible sample across reruns
    samples = []
    for intent in RELEVANT_INTENTS:
        rows = by_intent.get(intent, [])
        for category, instruction in rng.sample(rows, min(SAMPLES_PER_INTENT, len(rows))):
            text = PLACEHOLDER_RE.sub("#12345", instruction)
            samples.append(SampledMessage(intent=intent, category=category, text=text))
    return samples


def login(client: httpx.Client) -> str:
    resp = client.post("/auth/login", json={"email": OWNER_EMAIL, "password": DEMO_PASSWORD})
    resp.raise_for_status()
    return resp.json()["access_token"]


DISCLAIMER_MARKERS = ("don't have that information", "bilgim yok", "bir kişi", "a person will")


def looks_like_disclaimer(reply_text: str) -> bool:
    lowered = reply_text.lower()
    return any(marker in lowered for marker in DISCLAIMER_MARKERS)


def main() -> None:
    samples = load_samples()
    print(f"Sampled {len(samples)} messages across {len(RELEVANT_INTENTS)} intents.\n")

    with httpx.Client(base_url=BASE_URL, timeout=60) as client:
        token = login(client)
        client.headers["Authorization"] = f"Bearer {token}"

        results = []
        for i, sample in enumerate(samples, start=1):
            contact_id = f"bitext-stress-{sample.intent}-{i}"
            resp = client.post(
                "/test/conversations/messages",
                json={
                    "channel_type": "telegram",
                    "external_contact_id": contact_id,
                    "text": sample.text,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            outbound = next(
                (m for m in body["messages"] if m["direction"] == "outbound"), None
            )
            inbound = next(
                (m for m in body["messages"] if m["direction"] == "inbound"), None
            )
            diagnostics = (inbound or {}).get("diagnostics") or {}

            reply_text = (
                outbound["text"]
                if outbound
                else "(no reply -- escalated with no cover message?)"
            )
            result = {
                "intent": sample.intent,
                "category": sample.category,
                "message": sample.text,
                "detected_intent": diagnostics.get("detected_intent"),
                "lead_score": diagnostics.get("lead_score"),
                "decision": diagnostics.get("decision"),
                "escalated": body["escalated"],
                "reply": reply_text,
                "looks_like_disclaimer": looks_like_disclaimer(reply_text),
            }
            results.append(result)

            print(
                f"[{i}/{len(samples)}] {sample.intent:28s} -> "
                f"decision={result['decision']!s:16s} "
                f"escalated={result['escalated']!s:6s} "
                f"disclaimer={result['looks_like_disclaimer']}"
            )
            print(f"    Q: {sample.text}")
            print(f"    A: {reply_text}\n")

            if i < len(samples):
                time.sleep(DELAY_BETWEEN_MESSAGES_SECONDS)

    grounded = sum(
        1 for r in results if not r["looks_like_disclaimer"] and not r["escalated"]
    )
    disclaimed = sum(1 for r in results if r["looks_like_disclaimer"])
    escalated = sum(1 for r in results if r["escalated"])
    print(f"\n{'=' * 70}")
    print(
        f"Total: {len(results)}  Grounded answers: {grounded}  "
        f"Disclaimer: {disclaimed}  Escalated: {escalated}"
    )


if __name__ == "__main__":
    main()
