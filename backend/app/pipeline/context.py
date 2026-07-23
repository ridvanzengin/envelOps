from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PipelineContext:
    """Run-scoped dependencies for pipeline nodes, injected via LangGraph's
    Runtime mechanism (StateGraph's context_schema) -- never part of
    PipelineState, which gets checkpointed (docs/ARCHITECTURE.md §4) and
    can't hold a live DB session.

    One session per pipeline invocation (one message), shared across every
    node in that run for transactional consistency -- opened and closed by
    whoever calls graph.ainvoke(), not by the nodes themselves.
    """

    session: AsyncSession
