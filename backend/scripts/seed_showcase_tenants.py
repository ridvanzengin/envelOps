"""Multi-tenant showcase seed script (docs/ROADMAP.md §5.1) -- seeds
several fake tenants across different REQUIREMENTS §2 business-model
verticals (service/appointment, product/e-commerce, local/booking,
B2B/high-ticket), each with its own knowledge sources and settings, and a
small set of realistic conversations across two channel types (a chat
platform + email) run through the real pipeline -- so they show up, with
real intent/lead-score badges (docs/ROADMAP.md §3.3/§3.4), when browsing
the conversation rail as each tenant's seeded login.

Distinct from scripts/run_synthetic_conversations.py, which stays as-is:
that one is REQUIREMENTS §12 stage 1's pilot-validation gate for the real
honey-seller tenant specifically ("does this look right before pointing
real Instagram DMs at it"). This script is a demo/showcase generator --
occasional and on-demand, not a validation gate and not meant to run on
every change like a test suite.

Run directly (needs `docker compose up -d db` and a real
`ENVELOPS_GEMINI_API_KEY` in `.env`):

    cd backend && source .venv/bin/activate && python3 -m
    scripts.seed_showcase_tenants

Writes real rows (Tenant/User/Channel/KnowledgeSource/KnowledgeChunk/
Conversation/Message/PipelineTrace, plus whatever Lead/Escalation rows the
pipeline itself produces) tagged with recognizable tenant names, same
doesn't-clean-up-after-itself philosophy as run_synthetic_conversations.py.
Re-running this creates a fresh set of tenants each time rather than
reusing existing ones -- it's meant to be run occasionally to (re)populate
showcase data, not repeatedly expecting idempotency.

Kept small on purpose (13 messages across 4 tenants) to stay well inside
Gemini's free-tier throughput even with several tenants involved -- see
_DELAY_BETWEEN_MESSAGES_SECONDS's own reasoning in
run_synthetic_conversations.py; the same per-minute cap applies here,
just shared across more tenants instead of one.
"""

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import hash_password
from app.channels.models import Channel
from app.conversations.models import Conversation, Message
from app.core.db import async_session
from app.core.llm import embed_text
from app.knowledge.models import KnowledgeChunk, KnowledgeSource
from app.pipeline.repository import PipelineTraceRepository
from app.pipeline.runner import get_checkpointer, run_pipeline
from app.pipeline.state import PipelineState
from app.tenants.models import Tenant

_DELAY_BETWEEN_MESSAGES_SECONDS = 20.0

# Same password for every seeded login -- this is throwaway demo data,
# not real tenant credentials, so one memorable shared password beats
# generating and having to print/track a different one per tenant.
DEMO_PASSWORD = "EnvelOpsDemo!1"


@dataclass(frozen=True)
class TenantSpec:
    name: str
    slug: str
    closing_action: str
    closing_link: str | None
    chat_channel_type: str  # the four non-Telegram, non-email rail platforms
    knowledge: list[str]


@dataclass(frozen=True)
class ScenarioMessage:
    tenant_slug: str
    channel_key: str  # "chat" | "email" -- which of the tenant's two channels
    text: str


TENANTS: list[TenantSpec] = [
    # Service/appointment (REQUIREMENTS §2 row 1) -- health-tourism-like,
    # so the safety-floor edge cases here are genuinely on-topic, unlike
    # run_synthetic_conversations.py's honey tenant needing a contrived
    # trigger to exercise the same check.
    TenantSpec(
        name="Aurora Aesthetics Clinic",
        slug="aurora-clinic",
        closing_action="escalate_to_human",
        closing_link=None,
        chat_channel_type="whatsapp",
        knowledge=[
            "Rhinoplasty consultations are free and required before any "
            "procedure is scheduled -- pricing depends on the consultation.",
            "Typical recovery for facial procedures is 1-2 weeks of "
            "visible swelling; full results are usually seen after 3 months.",
            "We do not perform procedures on patients under 18 without "
            "parental consent and a documented medical reason.",
        ],
    ),
    # Product/e-commerce (REQUIREMENTS §2 row 2) -- a distinct showcase
    # tenant, not the real honey-seller pilot (that one stays isolated in
    # run_synthetic_conversations.py, not duplicated here).
    TenantSpec(
        name="Meadow & Jar Honey Co",
        slug="meadow-jar-honey",
        closing_action="book_or_checkout",
        closing_link="https://pay.example.com/meadow-jar-checkout",
        chat_channel_type="telegram",
        knowledge=[
            "We ship to the US, Canada, and EU; delivery takes 5-10 "
            "business days depending on destination.",
            "Jars come in 250g, 500g, and 1kg sizes, with discounts for "
            "orders of 6 or more (wedding favors, corporate gifts).",
            "Returns are accepted within 14 days if the seal is unbroken.",
        ],
    ),
    # Local/booking (REQUIREMENTS §2 row 3).
    TenantSpec(
        name="Luna Hair Studio",
        slug="luna-hair-studio",
        closing_action="book_or_checkout",
        closing_link="https://booking.example.com/luna-hair-studio",
        chat_channel_type="instagram",
        knowledge=[
            "Open Tuesday-Saturday, 9am-7pm. Closed Sundays and Mondays.",
            "Haircut + color packages start at $85; book at least a week "
            "ahead for weekend slots.",
            "Bridal party bookings (4+ people) need at least 2 weeks "
            "notice and a 20% non-refundable deposit.",
        ],
    ),
    # B2B/high-ticket (REQUIREMENTS §2 row 4) -- "almost always human-closed"
    # per that row, hence escalate_to_human even for a clearly hot lead.
    TenantSpec(
        name="Vertex Growth Partners",
        slug="vertex-growth-partners",
        closing_action="escalate_to_human",
        closing_link=None,
        chat_channel_type="facebook",
        knowledge=[
            "We specialize in growth marketing for B2B SaaS companies "
            "between Series A and Series C.",
            "Engagements start at $8,000/month, 3-month minimum, scoped "
            "after an initial discovery call.",
            "Recent client work includes a Series B fintech client that "
            "grew qualified pipeline 3x in two quarters.",
        ],
    ),
]

SCENARIOS: list[ScenarioMessage] = [
    # Aurora Aesthetics Clinic
    ScenarioMessage(
        "aurora-clinic", "chat", "Merhaba, burun estetiği için fiyat aralığı nedir?"
    ),
    ScenarioMessage(
        "aurora-clinic",
        "chat",
        "Can you guarantee this procedure has zero risk of complications?",
    ),
    ScenarioMessage(
        "aurora-clinic",
        "email",
        "Hi, I'm interested in a rhinoplasty consultation -- what's the process?",
    ),
    ScenarioMessage(
        "aurora-clinic",
        "email",
        "I've had some swelling and pain since my surgery last week, is that normal?",
    ),
    # Meadow & Jar Honey Co
    ScenarioMessage("meadow-jar-honey", "chat", "Hey! Do you ship to Canada?"),
    ScenarioMessage(
        "meadow-jar-honey",
        "chat",
        "I'd like to order 6 jars for wedding favors, what's the best price?",
    ),
    ScenarioMessage(
        "meadow-jar-honey",
        "email",
        "Good afternoon, could you tell me about your return policy?",
    ),
    # Luna Hair Studio
    ScenarioMessage(
        "luna-hair-studio",
        "chat",
        "Do you have any openings this Saturday for a haircut and color?",
    ),
    ScenarioMessage("luna-hair-studio", "chat", "What are your hours on Sundays?"),
    ScenarioMessage(
        "luna-hair-studio",
        "email",
        "Hi, I'd like to book a bridal party appointment for 6 people, is that possible?",
    ),
    # Vertex Growth Partners
    ScenarioMessage(
        "vertex-growth-partners", "chat", "What industries do you typically work with?"
    ),
    ScenarioMessage(
        "vertex-growth-partners",
        "chat",
        "We're a Series A startup with a $50k/month budget for growth "
        "marketing, can we set up a call?",
    ),
    ScenarioMessage(
        "vertex-growth-partners",
        "email",
        "Could you share a case study of a SaaS client you've helped scale?",
    ),
]


async def _setup_tenant(
    session: AsyncSession, spec: TenantSpec
) -> tuple[Tenant, dict[str, Channel]]:
    tenant = Tenant(
        id=uuid.uuid4(),
        name=spec.name,
        closing_action=spec.closing_action,
        closing_link=spec.closing_link,
    )
    session.add(tenant)
    await session.flush()

    session.add(
        User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            email=f"owner@{spec.slug}.demo",
            hashed_password=hash_password(DEMO_PASSWORD),
            role="owner",
        )
    )

    channels: dict[str, Channel] = {}
    for channel_key, channel_type in (
        ("chat", spec.chat_channel_type),
        ("email", "email"),
    ):
        channel = Channel(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            type=channel_type,
            external_account_id=f"demo-{spec.slug}-{channel_key}",
            is_test=True,
        )
        session.add(channel)
        channels[channel_key] = channel
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
    return tenant, channels


def _print_result(tenant_name: str, message: ScenarioMessage, result: dict) -> None:
    print(f"\n{'=' * 70}")
    print(f"[{tenant_name} / {message.channel_key}] {message.text}")
    print("-" * 70)
    if "__interrupt__" in result:
        interrupt = result["__interrupt__"][0]
        print("PAUSED (escalate_to_human) — awaiting human review")
        print(f"  reason: {interrupt.value.get('escalation_reason')}")
        return
    print(f"  intent:   {result.get('detected_intent')}")
    print(f"  score:    {result.get('lead_score')}")
    print(f"  decision: {result.get('decision')}")
    print(f"  reply:    {result.get('draft_text')}")


async def main() -> None:
    async with async_session() as session:
        tenants: dict[str, Tenant] = {}
        channels_by_tenant: dict[str, dict[str, Channel]] = {}
        conversations: dict[tuple[str, str], Conversation] = {}

        for spec in TENANTS:
            tenant, channels = await _setup_tenant(session, spec)
            tenants[spec.slug] = tenant
            channels_by_tenant[spec.slug] = channels
            print(f"Seeded tenant: {tenant.id} ({tenant.name})")
            print(f"  login: owner@{spec.slug}.demo / {DEMO_PASSWORD}")

        for scenario in SCENARIOS:
            key = (scenario.tenant_slug, scenario.channel_key)
            if key not in conversations:
                channel = channels_by_tenant[scenario.tenant_slug][scenario.channel_key]
                conversation = Conversation(
                    id=uuid.uuid4(),
                    tenant_id=channel.tenant_id,
                    channel_id=channel.id,
                    external_contact_id=f"demo-customer-{uuid.uuid4().hex[:8]}",
                )
                session.add(conversation)
                await session.commit()
                conversations[key] = conversation

        async with get_checkpointer() as checkpointer:
            for index, scenario in enumerate(SCENARIOS):
                tenant = tenants[scenario.tenant_slug]
                channel = channels_by_tenant[scenario.tenant_slug][scenario.channel_key]
                conversation = conversations[(scenario.tenant_slug, scenario.channel_key)]

                inbound_message = Message(
                    id=uuid.uuid4(),
                    tenant_id=tenant.id,
                    conversation_id=conversation.id,
                    direction="inbound",
                    text=scenario.text,
                )
                session.add(inbound_message)
                # Commit before run_pipeline -- CLAUDE.md's checkpointer
                # gotcha (an open transaction here has hung a checkpointed
                # run indefinitely before).
                await session.commit()

                state = PipelineState(
                    tenant_id=tenant.id,
                    conversation_id=conversation.id,
                    incoming_text=scenario.text,
                    channel_type=channel.type,
                )
                try:
                    result = await run_pipeline(state, session, checkpointer)
                    await PipelineTraceRepository(session).record_result(
                        tenant.id, conversation.id, inbound_message.id, result
                    )
                    if "__interrupt__" not in result:
                        draft_text = result.get("draft_text")
                        if draft_text:
                            session.add(
                                Message(
                                    id=uuid.uuid4(),
                                    tenant_id=tenant.id,
                                    conversation_id=conversation.id,
                                    direction="outbound",
                                    text=draft_text,
                                )
                            )
                    await session.commit()
                    _print_result(tenant.name, scenario, result)
                except Exception as exc:  # broad on purpose: report and keep going
                    print(f"\n{'=' * 70}")
                    print(f"[{tenant.name} / {scenario.channel_key}] {scenario.text}")
                    print(f"  ERROR: {exc!r}")

                if index < len(SCENARIOS) - 1:
                    await asyncio.sleep(_DELAY_BETWEEN_MESSAGES_SECONDS)

        print(f"\n{'=' * 70}")
        print("Done. Log in with any of the credentials printed above to browse")
        print("each tenant's seeded conversations in the rail.")


if __name__ == "__main__":
    asyncio.run(main())
