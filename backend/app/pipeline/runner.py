"""Compiles and invokes the pipeline graph — kept separate from graph.py,
which only defines the graph's structure/nodes (see escalate_to_human's
own docstring on why compiling belongs here, not there).

This is what makes the safety-gate pause (docs/ARCHITECTURE.md §5) durable:
a Postgres-backed checkpointer means the graph's paused state survives past
the current process, so "waits however long it takes a human to act" is
actually true, not just true until the next deploy/restart.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import publish_event
from app.pipeline.context import PipelineContext
from app.pipeline.graph import build_pipeline_graph
from app.pipeline.state import PipelineState


def _psycopg_conn_string() -> str:
    # AsyncPostgresSaver runs on psycopg (v3), not the asyncpg dialect the
    # rest of the app uses via SQLAlchemy -- same Postgres instance, two
    # different Python drivers, two different connection-string shapes.
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


@asynccontextmanager
async def get_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(_psycopg_conn_string()) as checkpointer:
        # Idempotent (CREATE ... IF NOT EXISTS under the hood) -- simpler to
        # call every time than to add a separate one-time-setup step
        # alongside Alembic's migrations for the domain tables. This is a
        # different schema-management mechanism than Alembic on purpose:
        # these tables belong to LangGraph, not to our own domain model.
        await checkpointer.setup()
        yield checkpointer


async def run_pipeline(
    state: PipelineState,
    session: AsyncSession,
    checkpointer: BaseCheckpointSaver,
) -> dict[str, Any]:
    """One thread per conversation (not per message) -- resuming after an
    escalation pause needs the same thread_id the interrupt happened on,
    and a conversation is the natural unit that spans multiple messages.

    Takes the abstract BaseCheckpointSaver, not AsyncPostgresSaver
    specifically -- get_checkpointer() above is what actually wires in
    Postgres for real use; this function itself doesn't care, which is
    what lets tests use the fast in-memory saver instead of needing a real
    database for every pause/resume test."""
    graph = build_pipeline_graph().compile(checkpointer=checkpointer)
    config: RunnableConfig = {"configurable": {"thread_id": str(state.conversation_id)}}
    context = PipelineContext(session=session)
    return await graph.ainvoke(state, config=config, context=context)


async def resume_pipeline(
    conversation_id: uuid.UUID,
    resume_value: Any,
    session: AsyncSession,
    checkpointer: BaseCheckpointSaver,
) -> dict[str, Any]:
    """Continues a run paused at escalate_to_human's interrupt() call, from
    wherever it left off -- same thread_id (conversation_id) the original
    run used. Whatever eventually resolves an escalation (the escalation
    queue screen, ARCHITECTURE §9 -- not built yet) calls this, not
    run_pipeline again; calling run_pipeline on an already-paused thread
    would just re-trigger the same interrupt rather than continuing past it.
    """
    graph = build_pipeline_graph().compile(checkpointer=checkpointer)
    config: RunnableConfig = {"configurable": {"thread_id": str(conversation_id)}}
    context = PipelineContext(session=session)
    return await graph.ainvoke(Command(resume=resume_value), config=config, context=context)


async def publish_pipeline_events(state: PipelineState, result: dict[str, Any]) -> None:
    """Fires the docs/ROADMAP.md §3.5 live-update events for one
    run_pipeline() call's outcome -- callers (pipeline/tasks.py,
    test_console/api.py) call this AFTER their own session.commit(), never
    from inside a graph node. decide_next_step/log_lead_and_notify
    (graph.py) run under the caller's still-open transaction -- publishing
    from there would race a listening frontend's refetch against a
    not-yet-durable commit, so this interprets run_pipeline()'s already-
    returned result instead of the graph publishing anything itself.

    Two independent things to check, not mutually exclusive: book_or_checkout's
    own missing-closing_link fallback (graph.py) sets both decision=
    escalate_to_human AND draft_text (an honest holding reply) in the same
    run, unlike the two interrupt()-based escalations, which only ever set
    one or the other.
    """
    escalated = "__interrupt__" in result
    if escalated:
        escalation_reason = result["__interrupt__"][0].value.get("escalation_reason")
    elif result.get("decision") == "escalate_to_human":
        escalation_reason = result.get("escalation_reason")
    else:
        escalation_reason = None

    if escalation_reason is not None:
        await publish_event(
            state.tenant_id,
            {
                "type": "escalation",
                "channel_type": state.channel_type,
                "conversation_id": str(state.conversation_id),
                "reason": escalation_reason,
            },
        )

    if result.get("draft_text"):
        await publish_event(
            state.tenant_id,
            {
                "type": "message",
                "channel_type": state.channel_type,
                "conversation_id": str(state.conversation_id),
            },
        )
