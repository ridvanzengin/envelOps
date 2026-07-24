"""One-time setup: creates a Channel row for a tenant's Telegram bot and
registers our webhook URL with Telegram (docs/ARCHITECTURE.md §8). No API
endpoint for this yet — channel connection isn't part of the API surface
(ARCHITECTURE §9) until real auth exists — so this is a script, not an
admin UI action.

Usage:

    cd backend && source .venv/bin/activate && python3 -m \\
        scripts.register_telegram_channel \\
        --tenant-id <uuid> \\
        --bot-token <token from @BotFather> \\
        --webhook-base-url https://your-public-domain.example

Needs a real, public HTTPS URL Telegram can reach — localhost doesn't
work. For local dev, expose it with a tunnel (ngrok, cloudflared, etc.)
first, then pass that tunnel's URL as --webhook-base-url.
"""

import argparse
import asyncio
import secrets
import uuid

from app.channels.models import Channel
from app.channels.telegram_client import get_me, set_webhook
from app.core.db import async_session
from app.tenants.models import Tenant


async def main(tenant_id: uuid.UUID, bot_token: str, webhook_base_url: str) -> None:
    async with async_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise SystemExit(f"No tenant with id {tenant_id}")

        # Also validates the token before we commit anything -- a typo'd
        # token would otherwise only surface later, as every webhook call
        # silently failing to reply.
        bot_info = await get_me(bot_token)
        username = bot_info.get("username", "unknown")

        webhook_secret = secrets.token_urlsafe(32)
        channel = Channel(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            type="telegram",
            external_account_id=str(username),
            bot_token=bot_token,
            webhook_secret=webhook_secret,
        )
        session.add(channel)
        await session.flush()

        webhook_url = (
            f"{webhook_base_url.rstrip('/')}/channels/telegram/{channel.id}/webhook"
        )
        await set_webhook(bot_token, webhook_url, webhook_secret)

        await session.commit()

        print(f"Channel created: {channel.id} (@{username})")
        print(f"Webhook registered: {webhook_url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, required=True)
    parser.add_argument("--bot-token", required=True)
    parser.add_argument("--webhook-base-url", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.tenant_id, args.bot_token, args.webhook_base_url))
