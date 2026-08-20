"""Unit tests for security primitives (bcrypt passwords, token hashing)."""

from __future__ import annotations

from app.core.security import (
    constant_time_equals,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self) -> None:
        hashed = hash_password("s3cret")
        assert hashed != "s3cret"
        assert verify_password("s3cret", hashed)

    def test_wrong_password_fails(self) -> None:
        hashed = hash_password("s3cret")
        assert not verify_password("nope", hashed)

    def test_garbage_hash_fails_cleanly(self) -> None:
        assert not verify_password("s3cret", "not-a-bcrypt-hash")

    def test_hashes_are_salted(self) -> None:
        assert hash_password("same") != hash_password("same")


class TestTokenHashing:
    def test_generate_token_is_urlsafe_and_long(self) -> None:
        token = generate_token()
        assert len(token) >= 40  # 32 bytes -> 43 base64url chars
        assert all(c.isalnum() or c in "-_" for c in token)

    def test_unique_tokens(self) -> None:
        assert generate_token() != generate_token()

    def test_hash_is_deterministic_and_one_way(self) -> None:
        token = generate_token()
        assert hash_token(token) == hash_token(token)
        assert len(hash_token(token)) == 64  # sha256 hex
        assert hash_token(token) != token

    def test_constant_time_equals(self) -> None:
        assert constant_time_equals("abc", "abc")
        assert not constant_time_equals("abc", "abd")
