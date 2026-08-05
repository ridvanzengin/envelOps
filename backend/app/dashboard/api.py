from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.core.db import get_session
from app.dashboard.service import DashboardSummary, compute_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Presets, not a free-form range -- matches the frontend's dropdown
# exactly (dataviz skill: "presets before a custom range"), and keeps the
# zero-filled conversations_trend loop in service.py bounded. Plain int,
# not Literal[1, 7, 30]: FastAPI/pydantic's query-param coercion doesn't
# convert the incoming string to int before matching an int Literal, so
# every request 422'd until this was found live -- see the manual check
# below instead.
_ALLOWED_RANGE_DAYS = (1, 7, 30)


@router.get("/summary")
async def get_summary(
    days: int = 7,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardSummary:
    if days not in _ALLOWED_RANGE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"days must be one of {_ALLOWED_RANGE_DAYS}",
        )
    return await compute_summary(session, current_user.tenant_id, days)
