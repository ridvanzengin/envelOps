from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.core.db import get_session
from app.core.demo_mode import block_in_demo_mode
from app.tenants.behavior_config import (
    BookOrCheckoutConfig,
    ChannelToneConfig,
    ClosingAction,
    ComplaintConfig,
    EscalationCoverConfig,
    GreetingConfig,
    KnowledgeQueryConfig,
    LeadHandlingConfig,
    OffTopicConfig,
    TenantBehaviorConfig,
    ToolCallingConfig,
    load_tenant_behavior_config,
)
from app.tenants.models import Tenant
from app.tenants.repository import TenantRepository

router = APIRouter(prefix="/tenants", tags=["tenants"])

# One tab's worth of fields at a time (frontend Settings.tsx: each tab has
# its own Save button, PATCHing only that tab's own slice) -- every field
# a plain area's full typed sub-model, never a deeper partial within an
# area, so Pydantic's own Literal/ge/le validation still applies exactly
# as before with zero hand-rolled checks.
_BEHAVIOR_AREA_FIELDS = (
    "greeting",
    "off_topic",
    "knowledge_query",
    "complaint",
    "lead_handling",
    "escalation_cover",
    "book_or_checkout",
    "tool_calling",
)


class TenantSettingsResponse(BaseModel):
    closing_action: ClosingAction
    closing_link: str | None
    behavior_config: TenantBehaviorConfig


class TenantSettingsPatch(BaseModel):
    """A tab's own slice, sent alone -- e.g. {"greeting": {...}} or
    {"closing_action": ..., "closing_link": ...}. Which top-level keys
    were actually sent is read from `model_fields_set`, not `is not
    None`, since closing_link/general_context are meaningfully nullable
    themselves (clearing one is a real, intentional patch)."""

    model_config = ConfigDict(extra="ignore")

    closing_action: ClosingAction | None = None
    closing_link: str | None = None
    greeting: GreetingConfig | None = None
    off_topic: OffTopicConfig | None = None
    knowledge_query: KnowledgeQueryConfig | None = None
    complaint: ComplaintConfig | None = None
    lead_handling: LeadHandlingConfig | None = None
    escalation_cover: EscalationCoverConfig | None = None
    book_or_checkout: BookOrCheckoutConfig | None = None
    tool_calling: ToolCallingConfig | None = None
    channel_overrides: dict[str, ChannelToneConfig] | None = None
    general_context: str | None = None


def _to_response(tenant: Tenant) -> TenantSettingsResponse:
    return TenantSettingsResponse(
        # Tenant.closing_action is plain str at the DB layer (CLAUDE.md:
        # validity enforced by code, not the type system) -- ClosingAction
        # narrows it for this typed response, same trust boundary
        # decide_next_step already relies on.
        closing_action=cast(ClosingAction, tenant.closing_action),
        closing_link=tenant.closing_link,
        behavior_config=load_tenant_behavior_config(tenant.behavior_config),
    )


@router.get("/settings")
async def get_tenant_settings(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TenantSettingsResponse:
    tenant = await TenantRepository(session).get(current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")
    return _to_response(tenant)


@router.patch("/settings")
async def patch_tenant_settings(
    body: TenantSettingsPatch,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(block_in_demo_mode),
) -> TenantSettingsResponse:
    tenant = await TenantRepository(session).get(current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found")

    provided = body.model_fields_set

    if "closing_action" in provided and body.closing_action is not None:
        tenant.closing_action = body.closing_action
    if "closing_link" in provided:
        tenant.closing_link = body.closing_link

    raw = dict(tenant.behavior_config)
    behavior_changed = False
    for field in _BEHAVIOR_AREA_FIELDS:
        value = getattr(body, field)
        if field in provided and value is not None:
            raw[field] = value.model_dump()
            behavior_changed = True
    if "channel_overrides" in provided and body.channel_overrides is not None:
        raw["channel_overrides"] = {
            key: override.model_dump() for key, override in body.channel_overrides.items()
        }
        behavior_changed = True
    if "general_context" in provided:
        raw["general_context"] = body.general_context
        behavior_changed = True
    if behavior_changed:
        tenant.behavior_config = raw

    await session.commit()
    return _to_response(tenant)
