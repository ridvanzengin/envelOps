"""One-off: seed every demo-stream DM template (app/pipeline/tasks.py's
_DEMO_STREAM_MESSAGES / _PURCHASE_INTENT_TEMPLATES / _HOT_LEAD_TEMPLATES /
_COMPLAINT_TEMPLATES / _ESCALATION_TRIGGER_MESSAGES) to every existing
tenant, once each -- built 2026-08-06 (direct instruction) to verify the
dangling-reference template fix (PR #72) and the secrets.choice
tenant-selection fix (PR #73) actually read right and land on every
tenant, rather than waiting on stream_demo_dm's own hourly/10-15-a-day
pacing to organically cover every category x tenant combination.

Deliberately reuses the real template pools and the real
ingest_inbound_message entry point (app/channels/service.py) -- same
find-or-create-conversation, persist, commit, publish-event, dispatch-
pipeline path a real inbound DM or stream_demo_dm's own hourly tick
takes, just looping over every tenant and every template instead of one
random tenant/one random template per call. Each message opens a brand-
new conversation (a fresh external_contact_id), matching the real
streamer's own "no prior turn to resolve a dangling pronoun against"
constraint.

Does NOT touch settings.demo_mode_enabled and doesn't need to --
ingest_inbound_message never checks it (unlike Test Console's own
send path, app/test_console/api.py's _send_test_message_demo) -- this
runs the same regardless of demo mode.

Pacing: ingest_inbound_message dispatches process_incoming_message via
Celery's .delay(), not synchronously -- the actual pipeline run (up to 4
sequential Gemini calls) happens in the already-running worker container
afterward, not in this script. app/core/llm.py has no retry/backoff on a
429, so firing all ~32-per-tenant messages at once would burst well past
the free tier's 15 req/min cap and most tasks would simply fail, not
queue and recover. _DELAY_BETWEEN_MESSAGES_SECONDS paces dispatches
generously against the worker's own --concurrency=2
(deploy/envelops/docker-compose.prod.yml) so in practice at most one or
two pipeline runs are ever in flight at once -- same reasoning as
scripts/run_synthetic_conversations.py's own 20s gap, just applied to
async dispatches instead of synchronous calls.

Run inside the backend container (needs the real DB + channel/pipeline
code) -- takes a while (64 messages * the delay below), so run it
detached rather than blocking a foreground shell:

    docker compose -p envelops --env-file deploy/envelops/.env.prod \
      -f deploy/envelops/docker-compose.prod.yml run --rm backend \
      python3 -m scripts.seed_demo_stream_dms

Not idempotent -- rerunning creates 32 more fresh conversations per
tenant on top of whatever's already there. This script doesn't clean up
after itself, same as run_synthetic_conversations.py; rely on
purge_stale_demo_data's rolling 7-day retention (demo mode only) or a
manual cleanup if that's not desired.
"""

import asyncio
import random
import secrets
import uuid

from app.channels.models import Channel
from app.channels.repository import ChannelRepository
from app.channels.service import ingest_inbound_message
from app.core.db import async_session
from app.pipeline.tasks import (
    _COMPLAINT_TEMPLATES,
    _DEMO_STREAM_CHANNEL_TYPES,
    _DEMO_STREAM_MESSAGES,
    _ESCALATION_TRIGGER_MESSAGES,
    _HOT_LEAD_TEMPLATES,
    _PURCHASE_INTENT_TEMPLATES,
    _random_order_number,
    _random_product_id,
    _random_reference,
)
from app.tenants.repository import TenantRepository

# See this module's own docstring for why this isn't just "as fast as
# possible" -- ingest_inbound_message's dispatch is fire-and-forget, the
# worker (--concurrency=2) is what actually burns Gemini quota, and
# app/core/llm.py doesn't retry a 429.
_DELAY_BETWEEN_MESSAGES_SECONDS = 25.0


def _all_messages() -> list[tuple[str, str]]:
    """(category, text) pairs -- every entry in every template pool,
    templates filled the same way _generate_demo_message() fills them
    (same random helpers, imported rather than reimplemented)."""
    messages: list[tuple[str, str]] = [("knowledge", text) for text in _DEMO_STREAM_MESSAGES]
    messages += [
        (
            "purchase_intent",
            t.format(qty=random.randint(1, 5), product=_random_product_id()),
        )
        for t in _PURCHASE_INTENT_TEMPLATES
    ]
    messages += [
        ("hot_lead", t.format(ref=_random_reference(), product=_random_product_id()))
        for t in _HOT_LEAD_TEMPLATES
    ]
    messages += [
        ("complaint", t.format(order_num=_random_order_number()))
        for t in _COMPLAINT_TEMPLATES
    ]
    messages += [
        ("escalation_trigger", t.format(product=_random_product_id()))
        for t in _ESCALATION_TRIGGER_MESSAGES
    ]
    return messages


async def _get_or_create_channel(
    channel_repo: ChannelRepository, tenant_id: uuid.UUID, channel_type: str
) -> Channel:
    channel = await channel_repo.get_demo_stream_channel(tenant_id, channel_type)
    if channel is not None:
        return channel
    return await channel_repo.add(
        Channel(
            tenant_id=tenant_id,
            type=channel_type,
            external_account_id=f"demo-stream-{channel_type}",
            is_test=False,
            bot_token=None,
            webhook_secret=secrets.token_urlsafe(32),
        )
    )


async def _seed() -> None:
    async with async_session() as session:
        tenant_rows = await TenantRepository(session).list_with_owner_unscoped()
        if not tenant_rows:
            print("No tenants found -- nothing to seed.")
            return

        channel_repo = ChannelRepository(session)
        total = 0
        for tenant, user in tenant_rows:
            messages = _all_messages()
            print(
                f"\n=== {tenant.name} ({user.email}) -- {len(messages)} messages ===",
                flush=True,
            )
            for i, (category, text) in enumerate(messages):
                channel_type = _DEMO_STREAM_CHANNEL_TYPES[i % len(_DEMO_STREAM_CHANNEL_TYPES)]
                channel = await _get_or_create_channel(channel_repo, tenant.id, channel_type)
                external_contact_id = f"demo-{uuid.uuid4().hex[:10]}"
                await ingest_inbound_message(channel, external_contact_id, text, session)
                total += 1
                print(
                    f"  [{total}] {tenant.name} / {channel_type} / {category}: "
                    f"{text[:80]!r}",
                    flush=True,
                )
                await asyncio.sleep(_DELAY_BETWEEN_MESSAGES_SECONDS)

        print(f"\nDispatched {total} messages across {len(tenant_rows)} tenant(s).")
        print(
            "Each dispatch queues a real process_incoming_message task -- replies "
            "land asynchronously as the worker processes the queue, not "
            "immediately. Check the conversation rail / dashboard in a few "
            "minutes, not right after this prints."
        )


if __name__ == "__main__":
    asyncio.run(_seed())
