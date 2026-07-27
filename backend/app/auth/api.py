from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.repository import UserRepository
from app.auth.security import create_access_token, verify_password
from app.core.db import get_session

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
