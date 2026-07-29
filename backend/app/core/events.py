import json
import logging
import uuid

import redis.asyncio as async_redis

from app.core.config import settings

logger = logging.getLogger(__name__)


async def publish_event(tenant_id: uuid.UUID, event: dict[str, str]) -> None:
    """Publishes to the one Redis channel app/events/api.py's SSE stream
    subscribes to for this tenant (docs/ROADMAP.md §3.5). Opens and closes
    its own connection per call rather than reusing a shared client --
    this is called both from FastAPI request handlers (one long-lived
    event loop, a shared client would be fine there) and from the Celery
    worker (app/pipeline/tasks.py, wrapped in a fresh asyncio.run() per
    task), where a client created on a previous, now-closed event loop
    would break. Publish frequency is a handful of times per inbound
    message, not a hot loop, so the extra connect/close isn't a real cost
    -- same tradeoff app/core/db.py already makes opening a fresh
    async_session() per Celery task rather than sharing one.

    Deliberately never raises -- a live-update push is a nice-to-have on
    top of the message/escalation rows every call site has already
    committed before calling this, not a guarantee those rows themselves
    depend on. A Redis blip here must not fail message ingestion or the
    pipeline run, same reasoning as pipeline/tasks.py already catching and
    logging (not swallowing, not raising) a Telegram delivery failure so
    it doesn't lose the Lead/Message rows already written.
    """
    try:
        client = async_redis.from_url(settings.redis_url)
        try:
            await client.publish(f"tenant-events:{tenant_id}", json.dumps(event))
        finally:
            await client.aclose()
    except Exception:
        logger.exception("Failed to publish live-update event for tenant %s", tenant_id)
