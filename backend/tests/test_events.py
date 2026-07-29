import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.events import publish_event


class TestPublishEvent:
    async def test_publishes_json_to_the_tenants_channel(self) -> None:
        tenant_id = uuid.uuid4()
        fake_client = MagicMock()
        fake_client.publish = AsyncMock()
        fake_client.aclose = AsyncMock()
        with patch("app.core.events.async_redis.from_url", return_value=fake_client):
            await publish_event(tenant_id, {"type": "message", "conversation_id": "abc"})

        expected_payload = json.dumps({"type": "message", "conversation_id": "abc"})
        fake_client.publish.assert_called_once_with(
            f"tenant-events:{tenant_id}", expected_payload
        )
        fake_client.aclose.assert_called_once()

    async def test_swallows_and_logs_a_connection_failure(self) -> None:
        # docs/ROADMAP.md §3.5 -- a live-update push is best-effort on top
        # of DB rows every call site has already committed before calling
        # this; a Redis blip here must never propagate into the caller
        # (which would otherwise fail message ingestion/the pipeline run
        # over what's just a nice-to-have).
        tenant_id = uuid.uuid4()
        fake_client = MagicMock()
        fake_client.publish = AsyncMock(side_effect=ConnectionError("redis is down"))
        fake_client.aclose = AsyncMock()
        with patch("app.core.events.async_redis.from_url", return_value=fake_client):
            await publish_event(tenant_id, {"type": "message"})  # must not raise

        fake_client.aclose.assert_called_once()
