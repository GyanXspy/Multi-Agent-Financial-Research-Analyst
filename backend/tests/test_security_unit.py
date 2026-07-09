"""
Tests for security.py — JWT encode/decode round-trip, expiry validation,
issuer/audience enforcement, password hash/verify, and token extraction.
"""

import time

import jwt as pyjwt
import pytest

# Environment must be set before importing app modules
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-only-padded-to-a-safe-length-000000")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stockanalyst.db")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")

from app.security import (
    JWT_AUDIENCE,
    JWT_ISSUER,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.config import settings


# ─── Password hashing ────────────────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_and_verify_match(self):
        plain = "secureP@ssw0rd!"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed)

    def test_wrong_password_rejected(self):
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_empty_password_handled(self):
        hashed = hash_password("")
        assert verify_password("", hashed)
        assert not verify_password("notempty", hashed)

    def test_different_hashes_for_same_password(self):
        """bcrypt uses unique salts, so two hashes of the same password differ."""
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2
        assert verify_password("samepassword", h1)
        assert verify_password("samepassword", h2)

    def test_verify_malformed_hash_returns_false(self):
        """Malformed hash should return False, not raise."""
        assert not verify_password("password", "not-a-valid-bcrypt-hash")


# ─── JWT ──────────────────────────────────────────────────────────────────────


class TestJWT:
    def test_round_trip(self):
        token = create_access_token(user_id=42, role="analyst")
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["role"] == "analyst"

    def test_contains_iss_and_aud(self):
        """F2: tokens must include issuer and audience claims."""
        token = create_access_token(user_id=1, role="admin")
        payload = decode_token(token)
        assert payload["iss"] == JWT_ISSUER
        assert payload["aud"] == JWT_AUDIENCE

    def test_expired_token_rejected(self):
        """A token that has already expired must be rejected."""
        # Manually create a token with an expiration in the past
        payload = {
            "sub": "1",
            "role": "analyst",
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,  # expired 1 hour ago
        }
        expired_token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        with pytest.raises(Exception) as exc_info:
            decode_token(expired_token)
        assert exc_info.value.status_code == 401

    def test_wrong_secret_rejected(self):
        """A token signed with a different secret must be rejected."""
        payload = {
            "sub": "1",
            "role": "analyst",
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        }
        bad_token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(Exception) as exc_info:
            decode_token(bad_token)
        assert exc_info.value.status_code == 401

    def test_wrong_issuer_rejected(self):
        """F2: a token with the wrong issuer must be rejected."""
        payload = {
            "sub": "1",
            "role": "analyst",
            "iss": "evil-service",
            "aud": JWT_AUDIENCE,
            "exp": int(time.time()) + 3600,
        }
        bad_token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        with pytest.raises(Exception) as exc_info:
            decode_token(bad_token)
        assert exc_info.value.status_code == 401

    def test_wrong_audience_rejected(self):
        """F2: a token with the wrong audience must be rejected."""
        payload = {
            "sub": "1",
            "role": "analyst",
            "iss": JWT_ISSUER,
            "aud": "other-audience",
            "exp": int(time.time()) + 3600,
        }
        bad_token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        with pytest.raises(Exception) as exc_info:
            decode_token(bad_token)
        assert exc_info.value.status_code == 401

    def test_missing_iss_aud_rejected(self):
        """A token without iss/aud claims must be rejected after F2 fix."""
        payload = {
            "sub": "1",
            "role": "analyst",
            "exp": int(time.time()) + 3600,
        }
        bad_token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        with pytest.raises(Exception) as exc_info:
            decode_token(bad_token)
        assert exc_info.value.status_code == 401

    def test_custom_expiry_respected(self):
        """When expires_minutes > 0, it overrides the default."""
        token = create_access_token(user_id=99, role="analyst", expires_minutes=5)
        payload = decode_token(token)
        # Token should be valid (we just created it with 5 min expiry)
        assert payload["sub"] == "99"

    def test_zero_expiry_uses_default(self):
        """When expires_minutes is 0, the default from config is used."""
        token = create_access_token(user_id=1, role="admin", expires_minutes=0)
        payload = decode_token(token)
        assert payload["sub"] == "1"
