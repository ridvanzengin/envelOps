import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.main import app


def _fake_escalation(tenant_id: uuid.UUID) -> MagicMock:
    escalation = MagicMock()
    escalation.id = uuid.uuid4()
    escalation.conversation_id = uuid.uuid4()
    escalation.tenant_id = tenant_id
    escalation.reason = "contraindication language (matched 'allerjik')"
    escalation.layer = "platform_floor"
    escalation.status = "pending"
    escalation.created_at = datetime.now(UTC)
    return escalation


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


async def _list_escalations(token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/escalations", headers=headers)


async def _resolve_escalation(escalation_id: uuid.UUID, token: str) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/escalations/{escalation_id}/resolve", headers=headers)


def _fake_trigger_phrase(tenant_id: uuid.UUID, phrase: str = "mad honey") -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.tenant_id = tenant_id
    row.phrase = phrase
    return row


async def _list_trigger_phrases(token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/escalations/trigger-phrases", headers=headers)


async def _add_trigger_phrase(phrase: str, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/escalations/trigger-phrases", json={"phrase": phrase}, headers=headers
        )


class TestListEscalations:
    async def test_rejects_missing_token(self) -> None:
        response = await _list_escalations(None)
        assert response.status_code == 401  # HTTPBearer's own "no credentials" code

    async def test_rejects_invalid_token(self) -> None:
        response = await _list_escalations("garbage")
        assert response.status_code == 401

    async def test_returns_only_the_caller_tenants_escalations(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="owner")
        escalation = _fake_escalation(tenant_id)

        with patch("app.escalation.api.EscalationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list = AsyncMock(return_value=[escalation])
            response = await _list_escalations(token)

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(escalation.id)
        assert body[0]["status"] == "pending"
        # list() was called scoped to the token's tenant, not a caller-supplied one
        mock_repo_cls.return_value.list.assert_called_once_with(tenant_id)


class TestResolveEscalation:
    async def test_rejects_missing_token(self) -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/escalations/{uuid.uuid4()}/resolve")
        assert response.status_code == 401

    async def test_404_when_not_found_or_wrong_tenant(self) -> None:
        token = create_access_token(
            user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner"
        )
        with patch("app.escalation.api.EscalationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _resolve_escalation(uuid.uuid4(), token)
        assert response.status_code == 404

    async def test_409_when_already_resolved(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        escalation = _fake_escalation(tenant_id)
        escalation.status = "resolved"
        with patch("app.escalation.api.EscalationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=escalation)
            response = await _resolve_escalation(escalation.id, token)
        assert response.status_code == 409

    async def test_marks_resolved_and_resumes_the_pipeline_thread(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        escalation = _fake_escalation(tenant_id)
        mock_checkpointer_cm = MagicMock()
        mock_checkpointer_cm.__aenter__ = AsyncMock(return_value="checkpointer")
        mock_checkpointer_cm.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("app.escalation.api.EscalationRepository") as mock_repo_cls,
            patch(
                "app.escalation.api.get_checkpointer", return_value=mock_checkpointer_cm
            ),
            patch(
                "app.escalation.api.resume_pipeline",
                AsyncMock(return_value={"decision": "escalate_to_human"}),
            ) as mock_resume,
        ):
            mock_repo_cls.return_value.get = AsyncMock(return_value=escalation)
            response = await _resolve_escalation(escalation.id, token)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "resolved"
        assert escalation.status == "resolved"
        args = mock_resume.call_args.args
        assert args[0] == escalation.conversation_id
        # Must be non-None -- Command(resume=None) breaks inside langgraph's
        # own internals (see app/escalation/api.py's comment); this is a
        # regression guard for that, not a check on what the value is.
        assert args[1] is not None
        assert args[3] == "checkpointer"


class TestListTriggerPhrases:
    async def test_rejects_missing_token(self) -> None:
        response = await _list_trigger_phrases(None)
        assert response.status_code == 401

    async def test_returns_only_the_callers_tenant_phrases(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        row = _fake_trigger_phrase(tenant_id)
        with patch("app.escalation.api.TenantTriggerPhraseRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list = AsyncMock(return_value=[row])
            response = await _list_trigger_phrases(token)

        assert response.status_code == 200
        body = response.json()
        assert body == [{"id": str(row.id), "phrase": "mad honey"}]
        mock_repo_cls.return_value.list.assert_called_once_with(tenant_id)


class TestAddTriggerPhrase:
    async def test_rejects_missing_token(self) -> None:
        response = await _add_trigger_phrase("mad honey", None)
        assert response.status_code == 401

    async def test_rejects_blank_phrase(self) -> None:
        response = await _add_trigger_phrase("   ", create_access_token(
            user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner"
        ))
        assert response.status_code == 400

    async def test_adds_a_stripped_phrase_scoped_to_the_callers_tenant(self) -> None:
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")
        row = _fake_trigger_phrase(tenant_id, phrase="mad honey")
        with patch("app.escalation.api.TenantTriggerPhraseRepository") as mock_repo_cls:
            mock_repo_cls.return_value.add = AsyncMock(return_value=row)
            response = await _add_trigger_phrase("  mad honey  ", token)

        assert response.status_code == 200
        body = response.json()
        assert body["phrase"] == "mad honey"
        added = mock_repo_cls.return_value.add.call_args.args[0]
        assert added.tenant_id == tenant_id
        assert added.phrase == "mad honey"
