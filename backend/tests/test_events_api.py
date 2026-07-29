import uuid

import httpx

from app.auth.security import create_access_token
from app.events.api import _subscribe
from app.main import app


class _FakePubSub:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self._messages = messages
        self.subscribed_to: str | None = None
        self.unsubscribed_from: str | None = None
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed_to = channel

    async def listen(self):
        for message in self._messages:
            yield message

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed_from = channel

    async def close(self) -> None:
        self.closed = True


class _FakeRedisClient:
    def __init__(self, pubsub: _FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


class TestSubscribe:
    async def test_yields_only_real_messages_decoded(self) -> None:
        # "subscribe" (not "psubscribe") replies with type=="subscribe" on
        # the connection's own ack -- must be skipped, same as any other
        # non-"message" entry, or the stream would emit a bogus first event.
        fake_pubsub = _FakePubSub(
            [
                {"type": "subscribe", "data": 1},
                {"type": "message", "data": b'{"type": "message", "conversation_id": "abc"}'},
                {"type": "message", "data": '{"type": "escalation"}'},
            ]
        )
        tenant_id = uuid.uuid4()
        client = _FakeRedisClient(fake_pubsub)

        received = [event async for event in _subscribe(client, tenant_id)]  # type: ignore[arg-type]

        assert received == [
            {"event": "update", "data": '{"type": "message", "conversation_id": "abc"}'},
            {"event": "update", "data": '{"type": "escalation"}'},
        ]
        assert fake_pubsub.subscribed_to == f"tenant-events:{tenant_id}"
        # The generator only unsubscribes/closes once the async for loop
        # above actually finishes draining _FakePubSub's fixed message
        # list (real Redis's listen() never ends on its own -- a live
        # connection only reaches the finally block on client disconnect).
        assert fake_pubsub.unsubscribed_from == f"tenant-events:{tenant_id}"
        assert fake_pubsub.closed is True


def _token(tenant_id: uuid.UUID | None = None) -> str:
    return create_access_token(
        user_id=uuid.uuid4(), tenant_id=tenant_id or uuid.uuid4(), role="owner"
    )


async def _get_stream(token: str | None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        params = {"token": token} if token is not None else {}
        return await client.get("/events/stream", params=params)


class TestStreamEventsAuth:
    async def test_rejects_missing_token(self) -> None:
        response = await _get_stream(None)
        assert response.status_code == 422

    async def test_rejects_invalid_token(self) -> None:
        response = await _get_stream("not-a-real-token")
        assert response.status_code == 401
