"""One-time setup: creates a Channel row for one of the simulated
integrations (Instagram/WhatsApp/Facebook/Email -- see
app/channels/simulated_client.py's docstring for why they're simulated,
not real). Mirrors scripts/register_telegram_channel.py's shape, minus
the two real-API calls (get_me, set_webhook) that have no equivalent
here -- there's no real platform to validate a token against or register
a webhook with.

Usage:

    cd backend && source .venv/bin/activate && python3 -m \\
        scripts.register_simulated_channel \\
        --tenant-id <uuid> \\
        --channel-type instagram|whatsapp|facebook|email

Prints the webhook URL (relative to wherever the API is running) and the
secret header value a caller needs to send inbound DMs through it, e.g.:

    curl -X POST http://localhost:8000/channels/instagram/<channel_id>/webhook \\
        -H "X-EnvelOps-Simulated-Webhook-Secret: <secret>" \\
        -H "Content-Type: application/json" \\
        -d '{"sender": {"id": "demo-customer"}, "message": {"text": "hi!"}}'
"""

import argparse
import asyncio
import secrets
import uuid

from app.channels.models import Channel
from app.core.db import async_session
from app.tenants.models import Tenant

_SIMULATED_CHANNEL_TYPES = ("instagram", "whatsapp", "facebook", "email")


async def main(tenant_id: uuid.UUID, channel_type: str) -> None:
    async with async_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise SystemExit(f"No tenant with id {tenant_id}")

        webhook_secret = secrets.token_urlsafe(32)
        channel = Channel(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            type=channel_type,
            external_account_id=f"simulated-{channel_type}",
            is_test=False,
            bot_token=None,
            webhook_secret=webhook_secret,
        )
        session.add(channel)
        await session.commit()

        print(f"Channel created: {channel.id} ({channel_type})")
        print(f"Webhook path: /channels/{channel_type}/{channel.id}/webhook")
        print(f"Secret header: X-EnvelOps-Simulated-Webhook-Secret: {webhook_secret}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, required=True)
    parser.add_argument("--channel-type", choices=_SIMULATED_CHANNEL_TYPES, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.tenant_id, args.channel_type))
