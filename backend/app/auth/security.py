"""Password hashing via stdlib PBKDF2-HMAC — no third-party crypto library
needed. JWT issuing/verification is a separate, not-yet-built piece: use a
vetted library (pyjwt) for that when it lands, don't hand-roll it."""

import hashlib
import hmac
import secrets

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
