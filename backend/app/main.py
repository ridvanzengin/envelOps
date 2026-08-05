import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.api import router as auth_router
from app.channels.api import router as channels_router
from app.commerce.fake_platform_api import router as fake_commerce_router
from app.conversations.api import router as conversations_router
from app.core.config import settings
from app.core.llm import AiProviderError
from app.dashboard.api import router as dashboard_router
from app.escalation.api import router as escalation_router
from app.events.api import router as events_router
from app.knowledge.api import router as knowledge_router
from app.leads.api import router as leads_router
from app.tenants.api import router as tenants_router
from app.test_console.api import router as test_console_router

logger = logging.getLogger(__name__)

app = FastAPI(title="EnvelOps")

# Only Test Console (app/test_console/api.py) currently runs the pipeline
# synchronously inside a request, so it's the one place a Gemini failure
# (app/core/llm.py's AiProviderError) can reach here today -- but this is
# registered globally, not route-specific, so any future synchronous AI
# call gets the same friendly response for free. The real exception detail
# (which model/quota/network cause) is logged server-side only -- the
# client-facing message stays generic on purpose, same reasoning as
# CLAUDE.md's Gemini quota notes: not something a Test Console user could
# act on, and not worth exposing provider/quota specifics for.
_AI_PROVIDER_UNAVAILABLE_MESSAGE = (
    "The AI provider is temporarily unavailable. Please try again in a moment."
)


@app.exception_handler(AiProviderError)
async def ai_provider_error_handler(request: Request, exc: AiProviderError) -> JSONResponse:
    logger.warning("AI provider error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": _AI_PROVIDER_UNAVAILABLE_MESSAGE})

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
