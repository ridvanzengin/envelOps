from fastapi import FastAPI

from app.auth.api import router as auth_router
from app.channels.api import router as channels_router
from app.commerce.fake_platform_api import router as fake_commerce_router
from app.conversations.api import router as conversations_router
from app.core.config import settings
from app.dashboard.api import router as dashboard_router
from app.escalation.api import router as escalation_router
from app.events.api import router as events_router
from app.knowledge.api import router as knowledge_router
from app.leads.api import router as leads_router
from app.tenants.api import router as tenants_router
from app.test_console.api import router as test_console_router

app = FastAPI(title="EnvelOps")

app.include_router(auth_router)
app.include_router(channels_router)
app.include_router(knowledge_router)
app.include_router(conversations_router)
app.include_router(leads_router)
app.include_router(escalation_router)
app.include_router(dashboard_router)
app.include_router(test_console_router)
app.include_router(events_router)
app.include_router(tenants_router)
app.include_router(fake_commerce_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/system/demo-mode")
async def demo_mode_status() -> dict[str, bool]:
    """Unauthenticated on purpose -- the frontend needs this before it
    even knows whether to show a login screen (App.tsx skips Login
    entirely and auto-authenticates as a showcase tenant when this is
    true, see auth/api.py's demo-login endpoints)."""
    return {"enabled": settings.demo_mode_enabled}
