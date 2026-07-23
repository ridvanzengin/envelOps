"""Thin wrapper around the Gemini API (docs/ARCHITECTURE.md §7 — one
provider covers both generation and embeddings). Pipeline nodes
(app/pipeline/graph.py) and knowledge ingestion should call these
functions, not the SDK directly, so swapping providers later stays the
"contained change" ARCHITECTURE §1 describes.

EMBEDDING_DIM must match `knowledge/models.py`'s `KnowledgeChunk.embedding`
column — text-embedding-004 has a fixed 768-dim output (unlike the newer
gemini-embedding-* models, which support configurable output size). If the
embedding model changes, both need updating together, plus a migration to
alter the existing column.
"""

from google import genai
from google.genai import types

from app.core.config import settings

GENERATION_MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIM = 768

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def generate_text(prompt: str) -> str:
    response = _get_client().models.generate_content(
        model=GENERATION_MODEL, contents=prompt
    )
    if response.text is None:
        # Could be a safety-filter block on Gemini's side, or a
        # function-call/non-text-only response — either way, silently
        # returning None where callers expect a reply is the wrong
        # failure mode for a pipeline that auto-sends by default.
        raise ValueError(f"Gemini returned no text content: {response!r}")
    return response.text


def embed_text(text: str, *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """task_type should be RETRIEVAL_DOCUMENT when embedding a knowledge
    chunk to store, and RETRIEVAL_QUERY when embedding an incoming question
    to search with — using the matching type is part of what makes Gemini's
    retrieval embeddings actually good, not an arbitrary label."""
    response = _get_client().models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    if not response.embeddings:
        raise ValueError(f"Gemini returned no embedding: {response!r}")
    values = response.embeddings[0].values
    if values is None:
        raise ValueError(f"Gemini returned an empty embedding vector: {response!r}")
    return values
