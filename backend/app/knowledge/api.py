import uuid
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.core.db import get_session
from app.core.llm import embed_text
from app.knowledge.chunking import chunk_text
from app.knowledge.html_text import extract_text
from app.knowledge.models import KnowledgeChunk, KnowledgeSource
from app.knowledge.repository import KnowledgeChunkRepository, KnowledgeSourceRepository
from app.knowledge.web_fetch import fetch_url

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class CreateKnowledgeSourceRequest(BaseModel):
    type: Literal["url", "manual"]
    url: str | None = None
    content: str | None = None


class UpdateKnowledgeSourceRequest(BaseModel):
    content: str


class KnowledgeSourceResponse(BaseModel):
    id: uuid.UUID
    type: str
    source_uri: str | None
    last_synced_at: datetime | None
    chunk_count: int
    # The chunked content joined back into one block (docs/ROADMAP.md --
    # "can't see or edit" gap found via live use). Reconstructed from
    # KnowledgeChunk rows, not stored separately anywhere: there's no
    # second copy of "the original text" to keep in sync with the chunks
    # actually used for retrieval.
    content: str


def _join_chunk_texts(chunks: list[str]) -> str:
    return "\n\n".join(chunks)


async def _ingest_chunks(
    session: AsyncSession, tenant_id: uuid.UUID, source_id: uuid.UUID, text: str
) -> list[str]:
    chunk_repo = KnowledgeChunkRepository(session)
    contents = chunk_text(text)
    for content in contents:
        embedding = embed_text(content)
        await chunk_repo.add(
            KnowledgeChunk(
                tenant_id=tenant_id,
                knowledge_source_id=source_id,
                content=content,
                embedding=embedding,
            )
        )
    return contents


async def _fetch_source_text(body: CreateKnowledgeSourceRequest) -> tuple[str, str | None]:
    """Returns (text_to_chunk, source_uri). Raises HTTPException on a bad
    request (missing field for the chosen type, or the URL fetch itself
    failing) -- both are the caller's problem to fix, not a 500."""
    if body.type == "url":
        if not body.url:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "url is required when type is 'url'"
            )
        try:
            html = await fetch_url(body.url)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"failed to fetch url: {exc}"
            ) from exc
        return extract_text(html), body.url

    if not body.content:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "content is required when type is 'manual'"
        )
    return body.content, None


@router.post("/sources")
async def create_knowledge_source(
    body: CreateKnowledgeSourceRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeSourceResponse:
    text, source_uri = await _fetch_source_text(body)
    if not text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no text content found to ingest")

    source_repo = KnowledgeSourceRepository(session)
    source = await source_repo.add(
        KnowledgeSource(
            tenant_id=current_user.tenant_id,
            type=body.type,
            source_uri=source_uri,
            last_synced_at=datetime.now(UTC),
        )
    )
    chunks = await _ingest_chunks(session, current_user.tenant_id, source.id, text)
    await session.commit()

    return KnowledgeSourceResponse(
        id=source.id,
        type=source.type,
        source_uri=source.source_uri,
        last_synced_at=source.last_synced_at,
        chunk_count=len(chunks),
        content=_join_chunk_texts(chunks),
    )


@router.get("/sources")
async def list_knowledge_sources(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeSourceResponse]:
    source_repo = KnowledgeSourceRepository(session)
    rows = await source_repo.list_with_chunks(current_user.tenant_id)
    return [
        KnowledgeSourceResponse(
            id=source.id,
            type=source.type,
            source_uri=source.source_uri,
            last_synced_at=source.last_synced_at,
            chunk_count=len(chunks),
            content=_join_chunk_texts([chunk.content for chunk in chunks]),
        )
        for source, chunks in rows
    ]


@router.post("/sources/{source_id}/refresh")
async def refresh_knowledge_source(
    source_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeSourceResponse:
    source_repo = KnowledgeSourceRepository(session)
    source = await source_repo.get(current_user.tenant_id, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge source not found")
    if source.type != "url":
        # Manual entries have nothing external to re-fetch (REQUIREMENTS
        # §5's re-sync requirement is about crawled content going stale on
        # the business's own site) -- editing one directly (PUT, below) or
        # deleting and re-adding are the ways to change it, not refresh.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{source.type}' sources have nothing to refresh; edit or delete instead",
        )
    if not source.source_uri:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "source has no url to refresh from")

    try:
        html = await fetch_url(source.source_uri)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"failed to fetch url: {exc}"
        ) from exc
    text = extract_text(html)
    if not text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no text content found to ingest")

    chunk_repo = KnowledgeChunkRepository(session)
    await chunk_repo.delete_by_source(current_user.tenant_id, source.id)
    chunks = await _ingest_chunks(session, current_user.tenant_id, source.id, text)
    source.last_synced_at = datetime.now(UTC)
    await session.commit()

    return KnowledgeSourceResponse(
        id=source.id,
        type=source.type,
        source_uri=source.source_uri,
        last_synced_at=source.last_synced_at,
        chunk_count=len(chunks),
        content=_join_chunk_texts(chunks),
    )


@router.put("/sources/{source_id}")
async def update_knowledge_source(
    source_id: uuid.UUID,
    body: UpdateKnowledgeSourceRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeSourceResponse:
    """Added 2026-07-29, alongside delete -- the other half of the "can't
    see or edit" gap found via live use: a manual entry's actual text was
    never shown anywhere, let alone editable, so the only way to correct
    one was delete-and-re-add. Manual sources only, symmetric with
    refresh's own url-only restriction above -- a url source's content
    comes from the url itself, so editing it by hand would just be
    silently overwritten by the next refresh; 400s instead of allowing
    that footgun."""
    source_repo = KnowledgeSourceRepository(session)
    source = await source_repo.get(current_user.tenant_id, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge source not found")
    if source.type != "manual":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{source.type}' sources can't be edited directly; refresh instead",
        )
    stripped = body.content.strip()
    if not stripped:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "content must not be blank")

    chunk_repo = KnowledgeChunkRepository(session)
    await chunk_repo.delete_by_source(current_user.tenant_id, source.id)
    chunks = await _ingest_chunks(session, current_user.tenant_id, source.id, stripped)
    source.last_synced_at = datetime.now(UTC)
    await session.commit()

    return KnowledgeSourceResponse(
        id=source.id,
        type=source.type,
        source_uri=source.source_uri,
        last_synced_at=source.last_synced_at,
        chunk_count=len(chunks),
        content=_join_chunk_texts(chunks),
    )


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_source(
    source_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Added 2026-07-29 -- previously the only way to correct a bad manual
    entry was refresh's own error message ("delete and re-add instead"),
    which wasn't actually possible since this endpoint didn't exist yet.
    Cascades to the source's own chunks via the same
    KnowledgeChunkRepository.delete_by_source refresh already uses, not a
    new deletion path."""
    source_repo = KnowledgeSourceRepository(session)
    source = await source_repo.get(current_user.tenant_id, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge source not found")

    await KnowledgeChunkRepository(session).delete_by_source(current_user.tenant_id, source_id)
    await source_repo.delete(source)
    await session.commit()
