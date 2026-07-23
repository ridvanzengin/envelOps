"""Thin wrapper around the Gemini API (docs/ARCHITECTURE.md §7 — one
provider covers both generation and embeddings). Pipeline nodes
(app/pipeline/graph.py) and knowledge ingestion should call these
functions, not the SDK directly, so swapping providers later stays the
"contained change" ARCHITECTURE §1 describes.

EMBEDDING_DIM must match `knowledge/models.py`'s `KnowledgeChunk.embedding`
column. text-embedding-004 (the original choice here) turned out to be
retired — gemini-embedding-001 replaced it and supports configurable
output size via output_dimensionality, so 768 is requested explicitly to
match the already-migrated column rather than taking the model's default
(3072). If the embedding model or dimension changes, both need updating
together, plus a migration to alter the existing column.
"""

from google import genai
from google.genai import types

from app.core.config import settings

GENERATION_MODEL = "gemini-flash-lite-latest"
# Free-tier quota is granted per model, not just per key/project, and it
# can be a persistent zero for a given model on a given account regardless
# of key validity (a 429 that never recovers, not a transient rate-limit
# blip) — confirmed against this same Google account via IoTOps's deploy
# notes (deploy/iotops/.env.prod.example), which hit the identical issue
# with gemini-2.0-flash/gemini-2.5-flash and settled on this model instead.
# If this model's quota ever changes, check what's actually available via
# `GET https://generativelanguage.googleapis.com/v1beta/models?key=...`
# rather than assuming any particular model name works.
EMBEDDING_MODEL = "gemini-embedding-001"
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
        config=types.EmbedContentConfig(
            task_type=task_type, output_dimensionality=EMBEDDING_DIM
        ),
    )
    if not response.embeddings:
        raise ValueError(f"Gemini returned no embedding: {response!r}")
    values = response.embeddings[0].values
    if values is None:
        raise ValueError(f"Gemini returned an empty embedding vector: {response!r}")
    return values
