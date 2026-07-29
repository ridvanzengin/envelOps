"""Live-update stream (docs/ROADMAP.md §3.5) -- no models.py/repository.py
here, same already-established exception app/test_console/ uses: there's
no new DB table backing this, just a Redis pub/sub relay, so the usual
per-module api.py/service.py/repository.py/models.py split doesn't apply.
"""

import uuid
from collections.abc import AsyncIterator

import redis.asyncio as async_redis
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.auth.dependencies import CurrentUser, get_current_user_from_query
from app.core.redis_client import get_async_redis_client

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream_events(
    current_user: CurrentUser = Depends(get_current_user_from_query),
    redis_client: async_redis.Redis = Depends(get_async_redis_client),
) -> EventSourceResponse:
    return EventSourceResponse(_subscribe(redis_client, current_user.tenant_id))


async def _subscribe(
    redis_client: async_redis.Redis, tenant_id: uuid.UUID
) -> AsyncIterator[dict[str, str]]:
    # Plain subscribe to exactly this tenant's own channel -- unlike
    # iotops-workspace's reference implementation (which pattern-subscribes
    # across every project in one connection, since a single connection
    # there isn't scoped to one tenant), each connection here is already
    # authenticated to one tenant, so there's nothing to pattern-match.
    channel = f"tenant-events:{tenant_id}"
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = message["data"]
            payload = data.decode() if isinstance(data, bytes) else data
            yield {"event": "update", "data": payload}
    finally:
        # Runs when the client disconnects (EventSourceResponse cancels
        # this generator) -- without it, every closed browser tab would
        # leak a subscription on this Redis connection forever.
        await pubsub.unsubscribe(channel)
        await pubsub.close()
