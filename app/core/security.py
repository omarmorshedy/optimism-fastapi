"""Security primitives: password hashing, token hashing, sessions, CSRF (ADR-005)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

import bcrypt

BCRYPT_ROUNDS = 12


# --- Password hashing --------------------------------------------------------


def hash_password(password: str, rounds: int = BCRYPT_ROUNDS) -> str:
    """Hash a password with bcrypt (cost 12). Returns the ``$2b$`` string."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification of a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# --- Random tokens & token hashing -------------------------------------------


def generate_token(nbytes: int = 32) -> str:
    """Cryptographically random, URL-safe token (default 32 bytes, base64url)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def hash_token(token: str) -> str:
    """One-way hash of a bearer token for storage.

    The raw token is 32 random bytes (256 bits) of entropy, so a keyed SHA-256
    digest provides the same brute-force protection as bcrypt while allowing
    indexed equality lookups (bcrypt's random salt makes direct lookup
    impossible). Password hashing still uses bcrypt cost 12 per ADR-005.
    """
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))
