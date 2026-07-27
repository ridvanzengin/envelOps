import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import InvalidTokenError, decode_access_token

_bearer_scheme = HTTPBearer()


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> CurrentUser:
    """Trusts the JWT signature/expiry (docs/ARCHITECTURE.md §2: tenant id
    embedded in the token) rather than re-querying the user on every
    request — no revocation list in Phase 1, single owner role, so there's
    nothing a fresh DB lookup would catch that the signature doesn't
    already guarantee."""
    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return CurrentUser(
        user_id=uuid.UUID(payload["sub"]),
        tenant_id=uuid.UUID(payload["tenant_id"]),
        role=payload["role"],
    )
