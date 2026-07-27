"""Password hashing via stdlib PBKDF2-HMAC — no third-party crypto library
needed. JWT issuing/verification uses pyjwt (docs/ARCHITECTURE.md §2:
tenant id embedded in the token), not hand-rolled."""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

_ALGORITHM = "sha256"
_ITERATIONS = 600_000  # OWASP 2023 minimum recommendation for PBKDF2-HMAC-SHA256
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_{_ALGORITHM}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm_label, iterations_str, salt_hex, digest_hex = encoded.split("$")
    except ValueError:
        return False
    if not algorithm_label.startswith("pbkdf2_"):
        return False
    algorithm = algorithm_label.removeprefix("pbkdf2_")
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    iterations = int(iterations_str)
    actual = hashlib.pbkdf2_hmac(algorithm, password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


class InvalidTokenError(Exception):
    """Raised for any token that fails to decode/verify — expired, wrong
    signature, or malformed. Callers don't need to distinguish which; all
    three are the same "not authenticated" outcome."""


def create_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, str]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if "sub" not in payload or "tenant_id" not in payload or "role" not in payload:
        raise InvalidTokenError("missing required claim")
    return payload
