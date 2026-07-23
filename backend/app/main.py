from fastapi import FastAPI

from app.auth.api import router as auth_router
from app.channels.api import router as channels_router
from app.conversations.api import router as conversations_router
from app.dashboard.api import router as dashboard_router
from app.escalation.api import router as escalation_router
from app.knowledge.api import router as knowledge_router
from app.leads.api import router as leads_router

app = FastAPI(title="EnvelOps")

app.include_router(auth_router)
app.include_router(channels_router)
app.include_router(knowledge_router)
app.include_router(conversations_router)
app.include_router(leads_router)
app.include_router(escalation_router)
app.include_router(dashboard_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
