"""One-tenant-at-a-time calibration seeding (docs/ROADMAP.md): seeds a
single new tenant (settings + a small hand-written knowledge base of
business-specific facts) and runs a batch of real customer-support DMs,
sampled from the Bitext dataset (see scripts/run_bitext_stress_test.py's
own docstring for provenance/download instructions), through the real
pipeline via the Test Console API -- so they show up as real, inspectable
conversations in the conversation rail (Channel.is_test=True, same
mechanism every other test conversation in this app already uses), not
just this script's own printed summary.

Workflow this was built for, by direct instruction: add one TenantSpec to
CALIBRATION_TENANTS below, run this script, then review live -- log in as
the tenant and check the seeded config on the Settings page, and browse
its sampled conversations on the rail. If the config needs adjusting,
edit the spec and rerun (harmless: a tenant whose login email already
exists is skipped, not duplicated or re-run). Once satisfied, append the
next tenant's spec and rerun again -- only the new spec gets processed.
Regression-test coverage (asserting each locked-in tenant's calibrated
messages still classify/decide the same way after later changes) is a
separate, not-yet-built follow-up, meant to start once a tenant's own
calibration pass is confirmed good -- not part of this script.

Prerequisites: same as run_bitext_stress_test.py -- `docker compose up`
(or backend + db running) with a real ENVELOPS_GEMINI_API_KEY and the
dataset CSV at backend/data/bitext_customer_support_27k.csv. Logs in
through the real POST /auth/login with the known DEMO_PASSWORD this
script itself sets on the tenant it just seeded -- not any no-password
bypass -- so this has no dependency on ENVELOPS_DEMO_MODE_ENABLED at all
(deliberately: that flag also makes Test Console stop persisting
messages, app/test_console/api.py's _send_test_message_demo, which would
silently defeat the entire point of this script).

Run directly (needs the API reachable at localhost:8000):

    cd backend && source .venv/bin/activate && python3 -m
    scripts.seed_calibration_tenant
"""

import asyncio
import csv
import random
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import hash_password
from app.channels.models import Channel
from app.core.db import async_session
from app.core.llm import embed_text
from app.knowledge.models import KnowledgeChunk, KnowledgeSource
from app.tenants.behavior_config import (
    BookOrCheckoutConfig,
    ComplaintConfig,
    TenantBehaviorConfig,
    ToolCallingConfig,
)
from app.tenants.models import Tenant

API_BASE_URL = "http://localhost:8000"
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "bitext_customer_support_27k.csv"
DEMO_PASSWORD = "EnvelOpsDemo!1"
DELAY_BETWEEN_MESSAGES_SECONDS = 20.0  # same free-tier headroom reasoning
# as run_synthetic_conversations.py / run_bitext_stress_test.py.

# Same curated subset run_bitext_stress_test.py established -- the
# categories that actually map onto a small DM seller's own knowledge
# base (ORDER/SHIPPING/CANCEL/DELIVERY/REFUND/PAYMENT). ACCOUNT/
# SUBSCRIPTION/INVOICE/CONTACT/FEEDBACK assume a self-service platform
# account system most of these businesses don't have -- a per-tenant
# spec can still override this with its own list if a given vertical
# needs a different subset (or none of this at all).
DEFAULT_RELEVANT_INTENTS = [
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

PLACEHOLDER_RE = re.compile(r"\{\{Order Number\}\}")


@dataclass(frozen=True)
class TenantSpec:
    name: str
    slug: str
    closing_action: str
    closing_link: str | None
    channel_type: str
    # Business-specific facts, hand-written the way a real owner would
    # phrase them -- plain data for the knowledge base, not instructions
    # (same DATA-not-behavior boundary TenantBehaviorConfig.additional_context
    # already draws).
    knowledge: list[str]
    behavior_config: dict[str, Any] = field(default_factory=dict)
    relevant_intents: list[str] = field(
        default_factory=lambda: list(DEFAULT_RELEVANT_INTENTS)
    )
    samples_per_intent: int = 2


# Tenant #1 -- squarely in Bitext's native domain (generic online-retail
# order/shipping/returns/payment questions), to prove out the whole
# seed -> sample -> review loop before tackling a vertical that needs
# more hand-authored, Bitext-uncovered scenarios (booking/appointment
# availability, B2B qualification, etc.).
CALIBRATION_TENANTS: list[TenantSpec] = [
    TenantSpec(
        name="Wildroot Apparel Co",
        slug="wildroot-apparel",
        closing_action="book_or_checkout",
        closing_link="https://pay.example.com/wildroot-checkout",
        channel_type="telegram",
        knowledge=[
            "Domestic orders ship within 1-2 business days and arrive in "
            "3-5 business days via USPS or UPS; international orders take "
            "10-14 business days and customs fees may apply.",
            "Wildroot runs true to size except the Oversized Hoodie line, "
            "which runs one size large -- check the size chart on each "
            "product page before ordering.",
            "Unworn items with tags attached can be returned within 30 "
            "days of delivery for a full refund; a prepaid return label "
            "is included in every package.",
            "Orders can be changed or cancelled within 1 hour of placing "
            "them; after that they're already in fulfillment and can't "
            "be modified.",
            "We accept Visa, Mastercard, Amex, PayPal, and Klarna "
            "installment payments (4 interest-free payments).",
        ],
        behavior_config=TenantBehaviorConfig(
            complaint=ComplaintConfig(empathetic_acknowledgment=True),
            book_or_checkout=BookOrCheckoutConfig(cta_style="direct_cta"),
            general_context=(
                "Wildroot Apparel Co is an online-only streetwear brand; "
                "no physical retail locations, ships from a single US "
                "warehouse."
            ),
        ).model_dump(),
    ),
    # Tenant #2 -- a different product category (electronics, not apparel)
    # to prove the config system genuinely varies per business, and the
    # first tenant with tool_calling enabled: order-status/inventory
    # questions are common and natural for an electronics retailer, so
    # this is a real exercise of the new fake-connector capability, not a
    # contrived one. Also the first tenant seeded on the new simulated
    # Instagram channel rather than Telegram.
    TenantSpec(
        name="Voltage Gadgets",
        slug="voltage-gadgets",
        closing_action="book_or_checkout",
        closing_link="https://pay.example.com/voltage-checkout",
        channel_type="instagram",
        knowledge=[
            "Orders ship within 1 business day; standard shipping takes "
            "3-5 business days domestically, express shipping (additional "
            "$15) arrives in 1-2 business days.",
            "All electronics come with a 1-year manufacturer warranty; "
            "extended 2-year protection plans are available at checkout "
            "for an additional fee.",
            "Unopened electronics can be returned within 15 days for a "
            "full refund; opened items are subject to a 15% restocking "
            "fee unless defective.",
            "We accept all major credit cards and PayPal; Klarna is not "
            "currently supported for electronics purchases due to our "
            "fraud-prevention policy.",
            "Orders can be modified within 30 minutes of placing them; "
            "after that they enter our fulfillment queue and can't be "
            "changed, only cancelled if not yet shipped.",
        ],
        behavior_config=TenantBehaviorConfig(
            complaint=ComplaintConfig(empathetic_acknowledgment=True),
            book_or_checkout=BookOrCheckoutConfig(cta_style="direct_cta"),
            tool_calling=ToolCallingConfig(
                order_status_lookup_enabled=True, inventory_check_enabled=True
            ),
            general_context=(
                "Voltage Gadgets is an online-only consumer electronics "
                "retailer specializing in smart home devices, wearables, "
                "and accessories; no physical retail locations."
            ),
        ).model_dump(),
    ),
]


def _load_bitext_samples(spec: TenantSpec) -> list[tuple[str, str, str]]:
    if not CSV_PATH.exists():
        raise SystemExit(
            f"{CSV_PATH} not found -- see run_bitext_stress_test.py's docstring"
        )
    by_intent: dict[str, list[tuple[str, str]]] = {}
    with CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            if row["intent"] in spec.relevant_intents:
                entry = (row["category"], row["instruction"])
                by_intent.setdefault(row["intent"], []).append(entry)

    # Seeded from the slug, not a fixed constant -- reproducible per
    # tenant across reruns, but distinct tenants don't all happen to
    # sample the exact same rows.
    rng = random.Random(hash(spec.slug) & 0xFFFFFFFF)
    samples = []
    for intent in spec.relevant_intents:
        rows = by_intent.get(intent, [])
        for category, instruction in rng.sample(rows, min(spec.samples_per_intent, len(rows))):
            text = PLACEHOLDER_RE.sub("#12345", instruction)
            samples.append((intent, category, text))
    return samples


async def _tenant_already_seeded(session: AsyncSession, spec: TenantSpec) -> bool:
    email = f"owner@{spec.slug}.demo"
    existing = await session.scalar(select(User).where(User.email == email))
    return existing is not None


async def _setup_tenant(session: AsyncSession, spec: TenantSpec) -> tuple[Tenant, User]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name=spec.name,
        closing_action=spec.closing_action,
        closing_link=spec.closing_link,
        behavior_config=spec.behavior_config,
    )
    session.add(tenant)
    await session.flush()

    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"owner@{spec.slug}.demo",
        hashed_password=hash_password(DEMO_PASSWORD),
        role="owner",
    )
    session.add(user)

    session.add(
        Channel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            type=spec.channel_type,
            external_account_id=f"demo-{spec.slug}",
            is_test=True,
        )
    )
    await session.flush()

    source = KnowledgeSource(id=uuid.uuid4(), tenant_id=tenant.id, type="manual")
    session.add(source)
    await session.flush()
    for text in spec.knowledge:
        session.add(
            KnowledgeChunk(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                knowledge_source_id=source.id,
                content=text,
                embedding=embed_text(text, task_type="RETRIEVAL_DOCUMENT"),
            )
        )
    await session.commit()
    return tenant, user


async def _login(client: httpx.AsyncClient, email: str) -> str:
    resp = await client.post("/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    resp.raise_for_status()
    return str(resp.json()["access_token"])


async def _run_calibration_messages(spec: TenantSpec, owner_email: str) -> None:
    samples = _load_bitext_samples(spec)
    print(
        f"\nSampled {len(samples)} messages across {len(spec.relevant_intents)} "
        f"intents for {spec.name}.\n"
    )

    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=60) as client:
        token = await _login(client, owner_email)
        client.headers["Authorization"] = f"Bearer {token}"

        results = []
        for i, (intent, _category, text) in enumerate(samples, start=1):
            contact_id = f"calib-{spec.slug}-{intent}-{i}"
            resp = await client.post(
                "/test/conversations/messages",
                json={
                    "channel_type": spec.channel_type,
                    "external_contact_id": contact_id,
                    "text": text,
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
                outbound["text"] if outbound else "(no reply -- escalated, no cover message?)"
            )
            result = {
                "intent": intent,
                "message": text,
                "detected_intent": diagnostics.get("detected_intent"),
                "lead_score": diagnostics.get("lead_score"),
                "decision": diagnostics.get("decision"),
                "escalated": body["escalated"],
                "reply": reply_text,
            }
            results.append(result)

            print(
                f"[{i}/{len(samples)}] {intent:28s} -> "
                f"decision={result['decision']!s:16s} escalated={result['escalated']!s:6s}"
            )
            print(f"    Q: {text}")
            print(f"    A: {reply_text}\n")

            if i < len(samples):
                await asyncio.sleep(DELAY_BETWEEN_MESSAGES_SECONDS)

    escalated = sum(1 for r in results if r["escalated"])
    print(f"\n{'=' * 70}")
    print(f"Total: {len(results)}  Escalated: {escalated}")
    print(f"{'=' * 70}")


async def main() -> None:
    async with async_session() as session:
        for spec in CALIBRATION_TENANTS:
            if await _tenant_already_seeded(session, spec):
                print(
                    f"Skipping {spec.name} -- already seeded "
                    f"(owner@{spec.slug}.demo exists)."
                )
                continue

            tenant, user = await _setup_tenant(session, spec)
            print(f"Seeded tenant: {tenant.id} ({tenant.name})")
            print(f"  login: owner@{spec.slug}.demo / {DEMO_PASSWORD}")

            await _run_calibration_messages(spec, user.email)

    print("\nDone. Log in with the credentials above to review the seeded")
    print("config on the Settings page and the sampled DMs on the rail.")


if __name__ == "__main__":
    asyncio.run(main())
