import unittest

from app.auth.security import hash_password, verify_password


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


if __name__ == "__main__":
    unittest.main()
