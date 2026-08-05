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

from dataclasses import dataclass
from typing import Any

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
# rather than assuming any particular model name works. Once it does work,
# it's still tight: this alias currently resolves to gemini-3.5-flash-lite,
# whose free tier caps at 15 requests/minute (measured live via
# scripts/run_synthetic_conversations.py) -- fine for one inbound DM at a
# time, but real batch/test usage needs deliberate pacing, not just "it
# has quota" being enough.
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768

_client: genai.Client | None = None


class AiProviderError(Exception):
    """Raised on any Gemini failure this module can't recover from --
    network error, auth, free-tier rate limit (see this file's own
    RESOURCE_EXHAUSTED notes below), or a response with no usable content.
    One type regardless of which of those it was, so a caller synchronously
    waiting on a reply (app/test_console/api.py, via app/main.py's own
    exception handler) can show one friendly, non-leaking message instead
    of a raw SDK exception reaching an HTTP response. Callers that don't
    run inside a request (app/pipeline/tasks.py's Celery tasks) are
    unaffected either way -- an uncaught exception there already just
    fails the task, same as before this type existed."""


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def generate_text(prompt: str) -> str:
    try:
        response = _get_client().models.generate_content(
            model=GENERATION_MODEL, contents=prompt
        )
    except Exception as exc:
        raise AiProviderError(str(exc)) from exc
    if response.text is None:
        # Could be a safety-filter block on Gemini's side, or a
        # function-call/non-text-only response — either way, silently
        # returning None where callers expect a reply is the wrong
        # failure mode for a pipeline that auto-sends by default.
        raise AiProviderError(f"Gemini returned no text content: {response!r}")
    return response.text


@dataclass(frozen=True)
class ToolDeclaration:
    name: str
    description: str
    parameters: dict[str, Any]  # plain JSON-schema dict, e.g.
    # {"type": "object", "properties": {...}, "required": [...]}


@dataclass(frozen=True)
class ToolCallRequest:
    name: str
    args: dict[str, Any]


def generate_with_tools(
    prompt: str, tool_declarations: list[ToolDeclaration]
) -> tuple[str | None, list[ToolCallRequest]]:
    """Real Gemini function-calling -- the model decides for itself whether
    a tool is needed at all (tool_config is deliberately left unset, which
    defaults to AUTO; that default is the actual mechanism that makes "the
    model genuinely decides" true, not a formality). Callers execute
    whatever calls come back themselves and fold the result into their own
    prompt -- this function does not send a FunctionResponse back to Gemini
    for a second turn, deliberately: that would be a second sequential
    Gemini call per tool-using message, on a pipeline already documented
    (docs/ROADMAP.md) as running up to several sequential free-tier-limited
    calls per inbound DM.

    Unlike generate_text, a None response.text here is the expected, common
    case (a pure function-call response has no text part) -- not an error,
    so this deliberately doesn't raise the way generate_text does."""
    declarations = [
        types.FunctionDeclaration(
            name=d.name, description=d.description, parameters_json_schema=d.parameters
        )
        for d in tool_declarations
    ]
    try:
        response = _get_client().models.generate_content(
            model=GENERATION_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=declarations)]
            ),
        )
    except Exception as exc:
        raise AiProviderError(str(exc)) from exc
    calls = [
        ToolCallRequest(name=call.name, args=dict(call.args or {}))
        for call in (response.function_calls or [])
        if call.name is not None
    ]
    return response.text, calls


def embed_text(text: str, *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """task_type should be RETRIEVAL_DOCUMENT when embedding a knowledge
    chunk to store, and RETRIEVAL_QUERY when embedding an incoming question
    to search with — using the matching type is part of what makes Gemini's
    retrieval embeddings actually good, not an arbitrary label."""
    try:
        response = _get_client().models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type=task_type, output_dimensionality=EMBEDDING_DIM
            ),
        )
    except Exception as exc:
        raise AiProviderError(str(exc)) from exc
    if not response.embeddings:
        raise AiProviderError(f"Gemini returned no embedding: {response!r}")
    values = response.embeddings[0].values
    if values is None:
        raise AiProviderError(f"Gemini returned an empty embedding vector: {response!r}")
    return values
