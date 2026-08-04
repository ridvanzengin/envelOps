"""Gate for every mutating endpoint when settings.demo_mode_enabled is on
(a public, read-only showcase deployment) -- see that flag's own docstring
in config.py for the full list of what it covers.

A FastAPI dependency, not a decorator: route functions already use
Depends() for auth/session, so this is the same shape (`Depends(block_in_demo_mode)`),
composes with them for free, and shows up in the generated OpenAPI schema
like any other dependency.
"""

from fastapi import HTTPException, status

from app.core.config import settings

DEMO_MODE_MESSAGE = (
    "This is a live demo — changes aren't saved. No data can be added, "
    "edited, or deleted here."
)


def block_in_demo_mode() -> None:
    if settings.demo_mode_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, DEMO_MODE_MESSAGE)
