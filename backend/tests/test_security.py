import time
import unittest
import uuid
from unittest.mock import patch

from app.auth.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class PasswordHashingTests(unittest.TestCase):
    def test_correct_password_verifies(self) -> None:
        encoded = hash_password("correct horse battery staple")
        self.assertTrue(verify_password("correct horse battery staple", encoded))

    def test_wrong_password_fails(self) -> None:
        encoded = hash_password("correct horse battery staple")
        self.assertFalse(verify_password("wrong password", encoded))

    def test_same_password_hashes_differently_each_time(self) -> None:
        first = hash_password("same password")
        second = hash_password("same password")
        self.assertNotEqual(first, second)

    def test_garbage_encoded_value_fails_closed(self) -> None:
        self.assertFalse(verify_password("anything", "not-a-valid-encoded-hash"))


class AccessTokenTests(unittest.TestCase):
    def test_roundtrip_carries_tenant_and_role(self) -> None:
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="owner")
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], str(user_id))
        self.assertEqual(payload["tenant_id"], str(tenant_id))
        self.assertEqual(payload["role"], "owner")

    def test_garbage_token_fails_closed(self) -> None:
        with self.assertRaises(InvalidTokenError):
            decode_access_token("not-a-real-token")

    def test_expired_token_fails_closed(self) -> None:
        with patch("app.auth.security.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret"
            mock_settings.jwt_algorithm = "HS256"
            mock_settings.jwt_expires_minutes = 0
            token = create_access_token(
                user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner"
            )
            time.sleep(1.1)
            with self.assertRaises(InvalidTokenError):
                decode_access_token(token)

    def test_tampered_signature_fails_closed(self) -> None:
        token = create_access_token(
            user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner"
        )
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        with self.assertRaises(InvalidTokenError):
            decode_access_token(tampered)


if __name__ == "__main__":
    unittest.main()
