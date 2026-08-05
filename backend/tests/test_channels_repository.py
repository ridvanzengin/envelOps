import uuid

from app.channels.repository import _build_demo_stream_channel_stmt

# Offline, no-DB statement-compilation test -- same approach
# tests/test_commerce_repository.py's _build_match_stmt tests already
# take, since this repo has no existing precedent for a real-DB
# repository test.


def _compiled_sql(stmt) -> str:  # type: ignore[no-untyped-def]
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


class TestBuildDemoStreamChannelStmt:
    def test_filters_by_tenant_and_type(self) -> None:
        tenant_id = uuid.uuid4()
        sql = _compiled_sql(_build_demo_stream_channel_stmt(tenant_id, "telegram"))
        assert "channels.tenant_id" in sql
        assert "channels.type" in sql

    def test_requires_is_test_false(self) -> None:
        sql = _compiled_sql(_build_demo_stream_channel_stmt(uuid.uuid4(), "telegram"))
        assert "channels.is_test" in sql

    def test_requires_bot_token_is_null(self) -> None:
        # The actual safety property: a real Telegram integration is also
        # is_test=False, so is_test alone can't rule it out -- bot_token
        # IS NULL is what stops the demo streamer from ever reusing a
        # channel that could trigger a real send.
        sql = _compiled_sql(_build_demo_stream_channel_stmt(uuid.uuid4(), "telegram"))
        assert "channels.bot_token IS NULL" in sql
