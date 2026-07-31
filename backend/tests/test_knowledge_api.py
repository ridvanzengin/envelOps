import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth.security import create_access_token
from app.core.db import get_session
from app.main import app


def _fake_source(tenant_id: uuid.UUID, **overrides: object) -> MagicMock:
    source = MagicMock()
    source.id = uuid.uuid4()
    source.tenant_id = tenant_id
    source.type = "manual"
    source.source_uri = None
    source.last_synced_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(source, key, value)
    return source


def _fake_chunk(content: str) -> MagicMock:
    chunk = MagicMock()
    chunk.content = content
    return chunk


@pytest.fixture(autouse=True)
def _override_session() -> object:
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


def _token(tenant_id: uuid.UUID | None = None) -> str:
    return create_access_token(
        user_id=uuid.uuid4(), tenant_id=tenant_id or uuid.uuid4(), role="owner"
    )


async def _post(path: str, body: dict, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=body, headers=headers)


async def _get(path: str, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def _delete(path: str, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.delete(path, headers=headers)


async def _put(path: str, body: dict, token: str | None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.put(path, json=body, headers=headers)


async def _post_file(
    path: str, filename: str, content: bytes, content_type: str, token: str | None
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            path, headers=headers, files={"file": (filename, content, content_type)}
        )


class TestCreateKnowledgeSource:
    async def test_rejects_missing_token(self) -> None:
        response = await _post("/knowledge/sources", {"type": "manual", "content": "x"}, None)
        assert response.status_code == 401

    async def test_manual_entry_chunks_and_embeds(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id)
        with (
            patch("app.knowledge.api.KnowledgeSourceRepository") as mock_source_repo_cls,
            patch("app.knowledge.api.KnowledgeChunkRepository") as mock_chunk_repo_cls,
            patch("app.knowledge.api.embed_text", return_value=[0.1, 0.2]),
        ):
            mock_source_repo_cls.return_value.add = AsyncMock(return_value=source)
            mock_chunk_repo_cls.return_value.add = AsyncMock()
            response = await _post(
                "/knowledge/sources",
                {"type": "manual", "content": "We ship worldwide via DHL."},
                token,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(source.id)
        assert body["type"] == "manual"
        assert body["source_uri"] is None
        assert body["chunk_count"] == 1
        mock_chunk_repo_cls.return_value.add.assert_called_once()
        stored_chunk = mock_chunk_repo_cls.return_value.add.call_args.args[0]
        assert stored_chunk.content == "We ship worldwide via DHL."
        assert stored_chunk.tenant_id == tenant_id

    async def test_manual_entry_requires_content(self) -> None:
        response = await _post("/knowledge/sources", {"type": "manual"}, _token())
        assert response.status_code == 400

    async def test_manual_entry_rejects_blank_content(self) -> None:
        response = await _post(
            "/knowledge/sources", {"type": "manual", "content": "   "}, _token()
        )
        assert response.status_code == 400

    async def test_url_entry_requires_url(self) -> None:
        response = await _post("/knowledge/sources", {"type": "url"}, _token())
        assert response.status_code == 400

    async def test_url_entry_fetches_and_extracts_text(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id, type="url", source_uri="https://example.com/faq")
        with (
            patch("app.knowledge.api.KnowledgeSourceRepository") as mock_source_repo_cls,
            patch("app.knowledge.api.KnowledgeChunkRepository") as mock_chunk_repo_cls,
            patch("app.knowledge.api.embed_text", return_value=[0.1]),
            patch(
                "app.knowledge.api.fetch_url",
                AsyncMock(return_value="<html><body><p>Shipping info here.</p></body></html>"),
            ),
        ):
            mock_source_repo_cls.return_value.add = AsyncMock(return_value=source)
            mock_chunk_repo_cls.return_value.add = AsyncMock()
            response = await _post(
                "/knowledge/sources",
                {"type": "url", "url": "https://example.com/faq"},
                token,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["source_uri"] == "https://example.com/faq"
        stored_chunk = mock_chunk_repo_cls.return_value.add.call_args.args[0]
        assert stored_chunk.content == "Shipping info here."

    async def test_url_fetch_failure_is_a_400_not_a_500(self) -> None:
        with patch(
            "app.knowledge.api.fetch_url",
            AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            response = await _post(
                "/knowledge/sources",
                {"type": "url", "url": "https://nope.example.com"},
                _token(),
            )
        assert response.status_code == 400

    async def test_url_with_no_extractable_text_is_a_400(self) -> None:
        with patch(
            "app.knowledge.api.fetch_url",
            AsyncMock(return_value="<html><body><script>noop()</script></body></html>"),
        ):
            response = await _post(
                "/knowledge/sources", {"type": "url", "url": "https://example.com"}, _token()
            )
        assert response.status_code == 400


class TestCreatePdfKnowledgeSource:
    async def test_rejects_missing_token(self) -> None:
        response = await _post_file(
            "/knowledge/sources/pdf", "doc.pdf", b"%PDF-1.4 fake", "application/pdf", None
        )
        assert response.status_code == 401

    async def test_rejects_non_pdf_file(self) -> None:
        response = await _post_file(
            "/knowledge/sources/pdf", "doc.txt", b"just text", "text/plain", _token()
        )
        assert response.status_code == 400

    async def test_rejects_oversized_file(self) -> None:
        oversized = b"x" * (10 * 1024 * 1024 + 1)
        response = await _post_file(
            "/knowledge/sources/pdf", "big.pdf", oversized, "application/pdf", _token()
        )
        assert response.status_code == 400

    async def test_rejects_unparseable_pdf(self) -> None:
        with patch(
            "app.knowledge.api.extract_pdf_text",
            side_effect=ValueError("not a valid PDF: bad EOF marker"),
        ):
            response = await _post_file(
                "/knowledge/sources/pdf",
                "doc.pdf",
                b"not really a pdf",
                "application/pdf",
                _token(),
            )
        assert response.status_code == 400

    async def test_rejects_pdf_with_no_extractable_text(self) -> None:
        with patch("app.knowledge.api.extract_pdf_text", return_value="   "):
            response = await _post_file(
                "/knowledge/sources/pdf", "blank.pdf", b"%PDF-1.4", "application/pdf", _token()
            )
        assert response.status_code == 400

    async def test_extracts_chunks_and_embeds(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id, type="pdf", source_uri="brochure.pdf")
        with (
            patch("app.knowledge.api.KnowledgeSourceRepository") as mock_source_repo_cls,
            patch("app.knowledge.api.KnowledgeChunkRepository") as mock_chunk_repo_cls,
            patch("app.knowledge.api.embed_text", return_value=[0.1]),
            patch(
                "app.knowledge.api.extract_pdf_text",
                return_value="Our return policy is 30 days.",
            ),
        ):
            mock_source_repo_cls.return_value.add = AsyncMock(return_value=source)
            mock_chunk_repo_cls.return_value.add = AsyncMock()
            response = await _post_file(
                "/knowledge/sources/pdf",
                "brochure.pdf",
                b"%PDF-1.4 fake bytes",
                "application/pdf",
                token,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "pdf"
        assert body["source_uri"] == "brochure.pdf"
        assert body["chunk_count"] == 1
        stored_source = mock_source_repo_cls.return_value.add.call_args.args[0]
        assert stored_source.type == "pdf"
        assert stored_source.source_uri == "brochure.pdf"
        assert stored_source.tenant_id == tenant_id
        stored_chunk = mock_chunk_repo_cls.return_value.add.call_args.args[0]
        assert stored_chunk.content == "Our return policy is 30 days."


class TestListKnowledgeSources:
    async def test_returns_only_the_callers_tenant_sources_with_counts_and_content(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id)
        chunks = [_fake_chunk("First chunk."), _fake_chunk("Second chunk.")]
        with patch("app.knowledge.api.KnowledgeSourceRepository") as mock_repo_cls:
            mock_repo_cls.return_value.list_with_chunks = AsyncMock(
                return_value=[(source, chunks)]
            )
            response = await _get("/knowledge/sources", token)

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(source.id)
        assert body[0]["chunk_count"] == 2
        assert body[0]["content"] == "First chunk.\n\nSecond chunk."
        mock_repo_cls.return_value.list_with_chunks.assert_called_once_with(tenant_id)


class TestRefreshKnowledgeSource:
    async def test_404_when_not_found(self) -> None:
        with patch("app.knowledge.api.KnowledgeSourceRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _post(f"/knowledge/sources/{uuid.uuid4()}/refresh", {}, _token())
        assert response.status_code == 404

    async def test_400_when_source_is_manual(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id, type="manual")
        with patch("app.knowledge.api.KnowledgeSourceRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=source)
            response = await _post(f"/knowledge/sources/{source.id}/refresh", {}, token)
        assert response.status_code == 400

    async def test_refetches_deletes_old_chunks_and_reembeds(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(
            tenant_id, type="url", source_uri="https://example.com/faq"
        )
        with (
            patch("app.knowledge.api.KnowledgeSourceRepository") as mock_source_repo_cls,
            patch("app.knowledge.api.KnowledgeChunkRepository") as mock_chunk_repo_cls,
            patch("app.knowledge.api.embed_text", return_value=[0.1]),
            patch(
                "app.knowledge.api.fetch_url",
                AsyncMock(return_value="<html><body><p>Updated info.</p></body></html>"),
            ),
        ):
            mock_source_repo_cls.return_value.get = AsyncMock(return_value=source)
            mock_chunk_repo_cls.return_value.delete_by_source = AsyncMock()
            mock_chunk_repo_cls.return_value.add = AsyncMock()
            response = await _post(f"/knowledge/sources/{source.id}/refresh", {}, token)

        assert response.status_code == 200
        body = response.json()
        assert body["chunk_count"] == 1
        mock_chunk_repo_cls.return_value.delete_by_source.assert_called_once_with(
            tenant_id, source.id
        )
        stored_chunk = mock_chunk_repo_cls.return_value.add.call_args.args[0]
        assert stored_chunk.content == "Updated info."


class TestDeleteKnowledgeSource:
    async def test_rejects_missing_token(self) -> None:
        response = await _delete(f"/knowledge/sources/{uuid.uuid4()}", None)
        assert response.status_code == 401

    async def test_404_when_not_found_or_wrong_tenant(self) -> None:
        with patch("app.knowledge.api.KnowledgeSourceRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _delete(f"/knowledge/sources/{uuid.uuid4()}", _token())
        assert response.status_code == 404

    async def test_deletes_source_and_its_chunks(self) -> None:
        # Any type, not just manual -- refresh has its own type-specific
        # rules, but delete doesn't need to care what kind of source this is.
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id, type="url", source_uri="https://example.com/faq")
        with (
            patch("app.knowledge.api.KnowledgeSourceRepository") as mock_source_repo_cls,
            patch("app.knowledge.api.KnowledgeChunkRepository") as mock_chunk_repo_cls,
        ):
            mock_source_repo_cls.return_value.get = AsyncMock(return_value=source)
            mock_source_repo_cls.return_value.delete = AsyncMock()
            mock_chunk_repo_cls.return_value.delete_by_source = AsyncMock()
            response = await _delete(f"/knowledge/sources/{source.id}", token)

        assert response.status_code == 204
        mock_chunk_repo_cls.return_value.delete_by_source.assert_called_once_with(
            tenant_id, source.id
        )
        mock_source_repo_cls.return_value.delete.assert_called_once_with(source)


class TestUpdateKnowledgeSource:
    async def test_rejects_missing_token(self) -> None:
        response = await _put(
            f"/knowledge/sources/{uuid.uuid4()}", {"content": "x"}, None
        )
        assert response.status_code == 401

    async def test_404_when_not_found_or_wrong_tenant(self) -> None:
        with patch("app.knowledge.api.KnowledgeSourceRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=None)
            response = await _put(
                f"/knowledge/sources/{uuid.uuid4()}", {"content": "x"}, _token()
            )
        assert response.status_code == 404

    async def test_400_when_source_is_not_manual(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id, type="url", source_uri="https://example.com/faq")
        with patch("app.knowledge.api.KnowledgeSourceRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=source)
            response = await _put(f"/knowledge/sources/{source.id}", {"content": "x"}, token)
        assert response.status_code == 400

    async def test_rejects_blank_content(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id, type="manual")
        with patch("app.knowledge.api.KnowledgeSourceRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get = AsyncMock(return_value=source)
            response = await _put(f"/knowledge/sources/{source.id}", {"content": "   "}, token)
        assert response.status_code == 400

    async def test_replaces_chunks_with_newly_chunked_content(self) -> None:
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id, type="manual")
        with (
            patch("app.knowledge.api.KnowledgeSourceRepository") as mock_source_repo_cls,
            patch("app.knowledge.api.KnowledgeChunkRepository") as mock_chunk_repo_cls,
            patch("app.knowledge.api.embed_text", return_value=[0.1]),
        ):
            mock_source_repo_cls.return_value.get = AsyncMock(return_value=source)
            mock_chunk_repo_cls.return_value.delete_by_source = AsyncMock()
            mock_chunk_repo_cls.return_value.add = AsyncMock()
            response = await _put(
                f"/knowledge/sources/{source.id}",
                {"content": "Corrected shipping info."},
                token,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["content"] == "Corrected shipping info."
        assert body["chunk_count"] == 1
        mock_chunk_repo_cls.return_value.delete_by_source.assert_called_once_with(
            tenant_id, source.id
        )
        stored_chunk = mock_chunk_repo_cls.return_value.add.call_args.args[0]
        assert stored_chunk.content == "Corrected shipping info."

    async def test_pdf_source_can_also_be_edited(self) -> None:
        # pdf joined manual on this endpoint's allow-list when pdf support
        # was added -- once extracted, a pdf's text has no stored original
        # to stay in sync with either, same "own text now" shape as manual.
        tenant_id = uuid.uuid4()
        token = _token(tenant_id)
        source = _fake_source(tenant_id, type="pdf", source_uri="brochure.pdf")
        with (
            patch("app.knowledge.api.KnowledgeSourceRepository") as mock_source_repo_cls,
            patch("app.knowledge.api.KnowledgeChunkRepository") as mock_chunk_repo_cls,
            patch("app.knowledge.api.embed_text", return_value=[0.1]),
        ):
            mock_source_repo_cls.return_value.get = AsyncMock(return_value=source)
            mock_chunk_repo_cls.return_value.delete_by_source = AsyncMock()
            mock_chunk_repo_cls.return_value.add = AsyncMock()
            response = await _put(
                f"/knowledge/sources/{source.id}",
                {"content": "Corrected from the brochure."},
                token,
            )

        assert response.status_code == 200
        assert response.json()["content"] == "Corrected from the brochure."
