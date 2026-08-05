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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import hash_password
from app.channels.models import Channel
from app.commerce.models import FakeCommerceProduct
from app.core.db import async_session
from app.core.llm import embed_text
from app.knowledge.chunking import chunk_text
from app.knowledge.models import KnowledgeChunk, KnowledgeSource
from app.tenants.behavior_config import (
    BookOrCheckoutConfig,
    ChannelToneConfig,
    ComplaintConfig,
    EscalationCoverConfig,
    GreetingConfig,
    KnowledgeQueryConfig,
    OffTopicConfig,
    TenantBehaviorConfig,
    ToolCallingConfig,
)
from app.tenants.models import Tenant

# Direct instruction (2026-08-05): every calibration tenant is
# formal/professional by default across the shared BusinessTone areas
# (greeting/off_topic/knowledge_query/escalation_cover below). Channel-
# level formality is deliberately narrower, not the same blanket
# treatment -- direct instruction the same day, after live-watching a
# WhatsApp/Telegram/Instagram/Facebook DM come back in a stiff "Dear
# customer... Best regards" register that reads wrong for a chat
# platform: only `email` gets an explicit formal_email override here.
# The other 4 channel types get no entry at all, which falls through to
# app/pipeline/behavior.py's own system default per channel (short and
# casual, no greeting/sign-off, "like a real person texting back") --
# not a second, redundant "casual" override, since that default already
# is exactly that.
_FORMAL_CHANNEL_OVERRIDES = {
    channel_type: ChannelToneConfig(
        formality="formal_email",
        include_greeting=True,
        include_sign_off=True,
        length_guidance="as_needed",
    )
    for channel_type in ("email",)
}

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
class CatalogItemSpec:
    """One app/commerce/models.py FakeCommerceProduct row -- the bounded
    catalog the fake commerce platform's inventory endpoint matches
    against (docs/plans/fake-commerce-platform-integration.md). Only
    meaningful for a tenant whose behavior_config has
    tool_calling.inventory_check_enabled=True; harmless but unused
    otherwise."""

    name: str
    size: str | None
    in_stock: bool
    quantity_available: int | None = None
    restock_eta_days: int | None = None


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
    catalog: list[CatalogItemSpec] = field(default_factory=list)
    # Two additional knowledge sources beyond the hand-written `knowledge`
    # facts above, added 2026-08-05 to round out a tenant's knowledge
    # library with the two source *types* (url, pdf) the real Knowledge
    # Sources UI supports but this script never exercised before -- both
    # empty by default (no-op) so existing behavior is unaffected unless a
    # spec opts in. Deliberately real multi-paragraph text run through the
    # actual chunk_text() splitter (see _setup_tenant below), not one
    # chunk per fact like `knowledge` above -- these are meant to look
    # like a genuinely-ingested FAQ page / PDF, not more hand-written
    # atomic facts.
    faq_content: str = ""
    terms_of_service_content: str = ""


_WILDROOT_FAQ = """Frequently Asked Questions

Q: Do you have a physical store?
A: No, Wildroot Apparel Co is an online-only streetwear brand. We ship
from a single warehouse in the United States.

Q: How long does shipping take?
A: Domestic orders ship within 1-2 business days and arrive in 3-5
business days via USPS or UPS. International orders take 10-14 business
days and customs fees may apply.

Q: What is your return policy?
A: Unworn items with tags attached can be returned within 30 days of
delivery for a full refund. A prepaid return label is included in every
package.

Q: Can I change or cancel my order?
A: Orders can be changed or cancelled within 1 hour of placing them.
After that, they're already in fulfillment and can't be modified.

Q: What payment methods do you accept?
A: We accept Visa, Mastercard, Amex, PayPal, and Klarna installment
payments (4 interest-free payments).

Q: How do I know what size to order?
A: Wildroot runs true to size except the Oversized Hoodie line, which
runs one size large. Check the size chart on each product page before
ordering.

Q: Do you offer gift cards?
A: Not at this time -- we're looking into adding gift cards in the
future.

Q: How can I contact customer support?
A: Message us directly here on any of our supported channels and one of
our team members (or our AI assistant) will get back to you."""

_WILDROOT_TERMS = """Terms of Service

Last updated: January 2026

1. Acceptance of Terms
By accessing or using the Wildroot Apparel Co website and messaging
channels, you agree to be bound by these Terms of Service. If you do not
agree to these terms, please do not use our services.

2. Use of Service
Wildroot Apparel Co provides an online retail service for streetwear
apparel. You must be at least 18 years old, or have parental consent, to
place an order. You agree to provide accurate and complete information
when placing an order.

3. Orders and Payment
All orders are subject to acceptance and availability. We accept Visa,
Mastercard, Amex, PayPal, and Klarna installment payments. Prices are
listed in US dollars and are subject to change without notice. We
reserve the right to refuse or cancel any order at our discretion,
including in cases of suspected fraud.

4. Shipping and Delivery
Domestic orders ship within 1-2 business days and arrive in 3-5 business
days via USPS or UPS. International orders take 10-14 business days;
customs fees may apply and are the responsibility of the customer.
Wildroot Apparel Co is not liable for delays caused by the carrier or
customs.

5. Returns and Refunds
Unworn items with tags attached can be returned within 30 days of
delivery for a full refund. A prepaid return label is included in every
package. Refunds are issued to the original payment method within 5-10
business days of receiving the returned item.

6. Intellectual Property
All content on our website and in our communications, including logos,
product designs, and text, is the property of Wildroot Apparel Co and
may not be reproduced without written permission.

7. Limitation of Liability
Wildroot Apparel Co is not liable for any indirect, incidental, or
consequential damages arising from the use of our products or services,
to the fullest extent permitted by law.

8. Changes to These Terms
We may update these Terms of Service from time to time. Continued use of
our services after changes are posted constitutes acceptance of the
revised terms.

9. Contact Us
If you have any questions about these Terms of Service, please reach out
to us through any of our supported messaging channels."""

_VOLTAGE_FAQ = """Frequently Asked Questions

Q: Do you have a physical store?
A: No, Voltage Gadgets is an online-only consumer electronics retailer.
We specialize in smart home devices, wearables, and accessories.

Q: How long does shipping take?
A: Orders ship within 1 business day. Standard shipping takes 3-5
business days domestically; express shipping (additional $15) arrives in
1-2 business days.

Q: Do your products come with a warranty?
A: All electronics come with a 1-year manufacturer warranty. Extended
2-year protection plans are available at checkout for an additional fee.

Q: What is your return policy?
A: Unopened electronics can be returned within 15 days for a full
refund. Opened items are subject to a 15% restocking fee unless
defective.

Q: What payment methods do you accept?
A: We accept all major credit cards and PayPal. Klarna is not currently
supported for electronics purchases due to our fraud-prevention policy.

Q: Can I change or cancel my order?
A: Orders can be modified within 30 minutes of placing them. After that,
they enter our fulfillment queue and can't be changed, only cancelled if
not yet shipped.

Q: Do you offer price matching?
A: We don't currently offer price matching, but we do run promotional
pricing during major sales periods like Black Friday and back-to-school
season.

Q: How can I contact customer support?
A: Message us directly here on any of our supported channels and one of
our team members (or our AI assistant) will get back to you."""

_VOLTAGE_TERMS = """Terms of Service

Last updated: January 2026

1. Acceptance of Terms
By accessing or using the Voltage Gadgets website and messaging
channels, you agree to be bound by these Terms of Service. If you do not
agree to these terms, please do not use our services.

2. Use of Service
Voltage Gadgets provides an online retail service for consumer
electronics, including smart home devices, wearables, and accessories.
You must be at least 18 years old, or have parental consent, to place an
order. You agree to provide accurate and complete information when
placing an order.

3. Orders and Payment
All orders are subject to acceptance and availability. We accept all
major credit cards and PayPal; Klarna is not currently supported for
electronics purchases due to our fraud-prevention policy. Prices are
listed in US dollars and are subject to change without notice. We
reserve the right to refuse or cancel any order at our discretion,
including in cases of suspected fraud.

4. Shipping and Delivery
Orders ship within 1 business day. Standard shipping takes 3-5 business
days domestically; express shipping is available for an additional fee.
Voltage Gadgets is not liable for delays caused by the carrier.

5. Warranty
All electronics come with a 1-year manufacturer warranty covering
defects in materials and workmanship. Extended 2-year protection plans
are available at checkout for an additional fee. The warranty does not
cover damage caused by misuse, accidents, or unauthorized modification.

6. Returns and Refunds
Unopened electronics can be returned within 15 days for a full refund.
Opened items are subject to a 15% restocking fee unless defective.
Refunds are issued to the original payment method within 5-10 business
days of receiving the returned item.

7. Intellectual Property
All content on our website and in our communications, including logos,
product descriptions, and text, is the property of Voltage Gadgets and
may not be reproduced without written permission.

8. Limitation of Liability
Voltage Gadgets is not liable for any indirect, incidental, or
consequential damages arising from the use of our products or services,
to the fullest extent permitted by law.

9. Changes to These Terms
We may update these Terms of Service from time to time. Continued use of
our services after changes are posted constitutes acceptance of the
revised terms.

10. Contact Us
If you have any questions about these Terms of Service, please reach out
to us through any of our supported messaging channels."""


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
            # Added 2026-08-05 to give the demo DM streamer's own question
            # set (app/pipeline/tasks.py's _DEMO_STREAM_MESSAGES) something
            # concrete to ground an ANSWERED reply in, instead of an
            # avoidable knowledge-gap escalation.
            "We don't offer a separate product warranty -- instead, if an "
            "item arrives damaged or defective, we offer a full refund "
            "or a free replacement -- reply with a photo of the issue "
            "and we'll take care of it right away, no need to wait for "
            "the standard 30-day return window.",
            "We run seasonal promotions and discount codes a few times a "
            "year, announced by email and on our social channels; there "
            "is no permanent storewide discount.",
            "Our best-selling item is the Oversized Hoodie, available in "
            "sizes S through XL; the Graphic Tee and Cargo Joggers are "
            "also customer favorites. We carry apparel from size XS "
            "through XXL depending on the style.",
            "Once an order ships, a tracking number is emailed "
            "automatically; a customer can also ask us for a real-time "
            "order status update at any time by providing their order "
            "number.",
        ],
        behavior_config=TenantBehaviorConfig(
            greeting=GreetingConfig(tone="formal_business"),
            off_topic=OffTopicConfig(tone="formal_business"),
            knowledge_query=KnowledgeQueryConfig(tone="formal_business"),
            complaint=ComplaintConfig(empathetic_acknowledgment=True),
            escalation_cover=EscalationCoverConfig(tone="formal_business"),
            book_or_checkout=BookOrCheckoutConfig(cta_style="direct_cta"),
            tool_calling=ToolCallingConfig(inventory_check_enabled=True),
            channel_overrides=dict(_FORMAL_CHANNEL_OVERRIDES),
            general_context=(
                "Wildroot Apparel Co is an online-only streetwear brand; "
                "no physical retail locations, ships from a single US "
                "warehouse."
            ),
        ).model_dump(),
        # Found live (2026-08-04): with no catalog at all, a hot "do you
        # have x icon in stock?" got book_or_checkout's ungrounded "Yes,
        # we do!" -- the exact fabrication bug the fake-commerce-platform
        # work exists to close, just never wired up for this tenant.
        # Oversized Hoodie matches the sizing-quirk knowledge chunk above
        # verbatim, so a calibration reviewer can cross-check the two.
        catalog=[
            CatalogItemSpec(
                name="Oversized Hoodie", size="S", in_stock=True, quantity_available=18
            ),
            CatalogItemSpec(
                name="Oversized Hoodie", size="M", in_stock=True, quantity_available=25
            ),
            CatalogItemSpec(
                name="Oversized Hoodie", size="L", in_stock=True, quantity_available=14
            ),
            CatalogItemSpec(
                name="Oversized Hoodie", size="XL", in_stock=False, restock_eta_days=7
            ),
            CatalogItemSpec(
                name="Graphic Tee", size="S", in_stock=True, quantity_available=40
            ),
            CatalogItemSpec(
                name="Graphic Tee", size="M", in_stock=True, quantity_available=52
            ),
            CatalogItemSpec(
                name="Graphic Tee", size="L", in_stock=True, quantity_available=31
            ),
            CatalogItemSpec(
                name="Cargo Joggers", size="M", in_stock=False, restock_eta_days=12
            ),
            CatalogItemSpec(
                name="Bucket Hat", size=None, in_stock=True, quantity_available=22
            ),
        ],
        faq_content=_WILDROOT_FAQ,
        terms_of_service_content=_WILDROOT_TERMS,
    ),
    # Tenant #2 -- a different product category (electronics, not apparel)
    # to prove the config system genuinely varies per business, the
    # second tenant with tool_calling enabled (Wildroot above is the
    # first as of 2026-08-04): order-status/inventory questions are
    # common and natural for an electronics retailer, so
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
            # Added 2026-08-05, found live: a demo-streamed "do you ship "
            # internationally?" escalated for lack of any documented
            # answer -- unlike Wildroot (which does ship internationally),
            # Voltage Gadgets deliberately doesn't, a realistic constraint
            # for a small electronics retailer (import/voltage-standard/
            # certification complexity varies a lot by country).
            "We currently ship only within the United States; "
            "international shipping is not available at this time.",
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
            # Added 2026-08-05, same reasoning as Wildroot's own new
            # chunks above -- gives the demo DM streamer's question set
            # something concrete to ground an ANSWERED reply in.
            "A damaged or defective item is always eligible for a full "
            "refund or replacement, regardless of the 15-day return "
            "window or restocking fee that applies to non-defective "
            "returns -- just let us know and send a photo if possible.",
            "We don't run a fixed year-round discount, but we do offer "
            "promotional pricing during major sales periods like Black "
            "Friday and back-to-school season.",
            "Our most popular product is the SmartHome Hub X1, our "
            "flagship smart-home device; the Wireless Earbuds Pro and "
            "Portable Power Bank are also top sellers.",
            "Our wearable devices, like the FitTrack Band, come in S/M/L "
            "band sizes; all of our other electronics (hubs, earbuds, "
            "power banks, smart plugs) are one-size.",
            "Once an order ships, a tracking number is emailed "
            "automatically; a customer can also ask us for a real-time "
            "order status update at any time by providing their order "
            "number.",
        ],
        behavior_config=TenantBehaviorConfig(
            greeting=GreetingConfig(tone="formal_business"),
            off_topic=OffTopicConfig(tone="formal_business"),
            knowledge_query=KnowledgeQueryConfig(tone="formal_business"),
            complaint=ComplaintConfig(empathetic_acknowledgment=True),
            escalation_cover=EscalationCoverConfig(tone="formal_business"),
            book_or_checkout=BookOrCheckoutConfig(cta_style="direct_cta"),
            tool_calling=ToolCallingConfig(
                order_status_lookup_enabled=True, inventory_check_enabled=True
            ),
            channel_overrides=dict(_FORMAL_CHANNEL_OVERRIDES),
            general_context=(
                "Voltage Gadgets is an online-only consumer electronics "
                "retailer specializing in smart home devices, wearables, "
                "and accessories; no physical retail locations."
            ),
        ).model_dump(),
        # The only tenant seeded with a catalog so far -- the only one
        # with inventory_check_enabled=True above, so this is the one a
        # calibration reviewer can actually exercise the bounded-catalog
        # fix against (e.g. asking about "AK-47" and getting a genuine
        # "we don't carry that" instead of a fabricated stock answer).
        catalog=[
            CatalogItemSpec(
                name="SmartHome Hub X1", size=None, in_stock=True, quantity_available=34
            ),
            CatalogItemSpec(
                name="Wireless Earbuds Pro", size=None, in_stock=True, quantity_available=58
            ),
            CatalogItemSpec(
                name="FitTrack Band", size="S", in_stock=True, quantity_available=20
            ),
            CatalogItemSpec(
                name="FitTrack Band", size="M", in_stock=True, quantity_available=12
            ),
            CatalogItemSpec(
                name="FitTrack Band", size="L", in_stock=False, restock_eta_days=9
            ),
            CatalogItemSpec(
                name="Smart Plug 4-Pack", size=None, in_stock=False, restock_eta_days=14
            ),
            CatalogItemSpec(
                name="Portable Power Bank 20000mAh",
                size=None,
                in_stock=True,
                quantity_available=76,
            ),
        ],
        faq_content=_VOLTAGE_FAQ,
        terms_of_service_content=_VOLTAGE_TERMS,
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


async def _add_chunked_source(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    source_type: str,
    source_uri: str,
    text: str,
) -> None:
    """Seeds one KnowledgeSource + its chunks from a long text block, run
    through the real chunk_text() splitter -- unlike `knowledge`'s one-
    chunk-per-hand-written-fact in _setup_tenant below, this is meant to
    look like a genuinely-ingested multi-paragraph document (an FAQ page,
    a Terms of Service PDF), the same shape a real url/pdf upload through
    app/knowledge/api.py would produce.

    Never actually fetches source_uri or parses a real PDF file -- and
    deliberately doesn't need to: app/knowledge/api.py's own docstrings
    note this app never retains the original HTML/PDF bytes after
    ingestion anyway, only the extracted+chunked text, so hand-seeding
    that text directly produces an identical end state to a real fetch/
    parse, for a fraction of the complexity and no new dependency (a
    PDF-writing library isn't otherwise needed anywhere in this app).

    For type="url" sources specifically, source_uri uses the `.invalid`
    TLD (RFC 2606 -- reserved, guaranteed to never resolve), not
    `.example.com` like Tenant.closing_link elsewhere in this script --
    deliberately different choice: closing_link is only ever rendered as
    text in a reply, never fetched by this app's own code, while a url
    KnowledgeSource's source_uri *can* be (a real "Refresh" click calls
    app/knowledge/api.py's refresh_knowledge_source, which does a real
    fetch_url). `.example.com` actually resolves (to a real placeholder
    page) and would silently overwrite this hand-seeded FAQ content with
    garbage; `.invalid` fails DNS resolution cleanly, so a refresh
    attempt gets an honest "failed to fetch url" 400 instead of silent
    corruption -- acceptable either way since demo mode blocks refresh
    entirely (app/core/demo_mode.py), and outside demo mode this is the
    same calibration-review-only workflow this whole script exists for."""
    source = KnowledgeSource(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        type=source_type,
        source_uri=source_uri,
        last_synced_at=datetime.now(UTC),
    )
    session.add(source)
    await session.flush()
    for chunk_content in chunk_text(text):
        session.add(
            KnowledgeChunk(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                knowledge_source_id=source.id,
                content=chunk_content,
                embedding=embed_text(chunk_content, task_type="RETRIEVAL_DOCUMENT"),
            )
        )


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
    if spec.faq_content:
        await _add_chunked_source(
            session,
            tenant.id,
            "url",
            f"https://{spec.slug.replace('-', '')}.invalid/faq",
            spec.faq_content,
        )
    if spec.terms_of_service_content:
        await _add_chunked_source(
            session,
            tenant.id,
            "pdf",
            f"{spec.slug}-terms-of-service.pdf",
            spec.terms_of_service_content,
        )
    for item in spec.catalog:
        session.add(
            FakeCommerceProduct(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                name=item.name,
                size=item.size,
                in_stock=item.in_stock,
                quantity_available=item.quantity_available,
                restock_eta_days=item.restock_eta_days,
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
