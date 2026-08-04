import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.repository import UserRepository
from app.auth.security import create_access_token, verify_password
from app.core.config import settings
from app.core.db import get_session
from app.tenants.repository import TenantRepository

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login")
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    user_repo = UserRepository(session)
    user = await user_repo.get_by_email_unscoped(body.email)
    # Same generic message whether the email doesn't exist or the password
    # is wrong -- confirming which would let a caller enumerate accounts.
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")

    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    return TokenResponse(access_token=token)


class DemoTenantOption(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    email: str


class DemoLoginRequest(BaseModel):
    user_id: uuid.UUID


def _require_demo_mode_enabled() -> None:
    # 404, not 403 -- a real deployment with this off shouldn't even
    # reveal the feature exists, not just refuse it. Used to also accept
    # a separate general-purpose dev_auth_bypass_enabled flag; removed
    # (decided 2026-08-04) once demo mode covered the same no-password
    # tenant switch need -- this is now solely demo mode's own mechanism
    # (the Dashboard's tenant dropdown), safe to open up specifically
    # because demo mode's own write-blocking means there's nothing an
    # anonymous visitor could do with it beyond picking which showcase
    # tenant to look at.
    if not settings.demo_mode_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.get("/demo-tenants")
async def list_demo_tenants(
    session: AsyncSession = Depends(get_session),
) -> list[DemoTenantOption]:
    """Demo mode's tenant switcher (docs/ROADMAP.md) -- lists every tenant
    with a login, for the Dashboard's own dropdown that skips the email/
    password form entirely. See settings.demo_mode_enabled's own
    docstring for why this must never be reachable outside a demo
    deployment."""
    _require_demo_mode_enabled()
    rows = await TenantRepository(session).list_with_owner_unscoped()
    return [
        DemoTenantOption(
            user_id=user.id, tenant_id=tenant.id, tenant_name=tenant.name, email=user.email
        )
        for tenant, user in rows
    ]


@router.post("/demo-login")
async def demo_login(
    body: DemoLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Mints a real token for the chosen user with no password check at
    all -- the entire point of this endpoint. Same gating and reasoning as
    GET /demo-tenants above."""
    _require_demo_mode_enabled()
    user = await UserRepository(session).get_by_id_unscoped(body.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    return TokenResponse(access_token=token)
