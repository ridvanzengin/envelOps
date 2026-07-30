from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.core.db import get_session
from app.tenants.behavior_config import (
    ClosingAction,
    TenantBehaviorConfig,
    load_tenant_behavior_config,
)
from app.tenants.repository import TenantRepository

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantSettingsResponse(BaseModel):
    """Same model both directions (GET response and PUT request) --
    closing_action/closing_link/behavior_config are the entire editable
    surface, nothing to exclude the way create/update pairs elsewhere
    need to (see the plan this was built from)."""

    closing_action: ClosingAction
    closing_link: str | None
    behavior_config: TenantBehaviorConfig


@router.get("/settings")
async def get_tenant_settings(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TenantSettingsResponse:
    tenant = await TenantRepository(session).get(current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
    return TenantSettingsResponse(
        # Tenant.closing_action is plain str at the DB layer (CLAUDE.md:
        # validity enforced by code, not the type system) -- ClosingAction
        # narrows it for this typed response, same trust boundary
        # decide_next_step already relies on.
        closing_action=cast(ClosingAction, tenant.closing_action),
        closing_link=tenant.closing_link,
        behavior_config=load_tenant_behavior_config(tenant.behavior_config),
    )


@router.put("/settings")
async def update_tenant_settings(
    body: TenantSettingsResponse,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TenantSettingsResponse:
    tenant = await TenantRepository(session).get(current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
    tenant.closing_action = body.closing_action
    tenant.closing_link = body.closing_link
    tenant.behavior_config = body.behavior_config.model_dump()
    await session.commit()
    return body
