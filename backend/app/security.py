"""Password hashing (PBKDF2-HMAC-SHA256, 310k iterations, per-user salt) and
JWT session tokens backed by a server-side session table (so logout really
revokes the token)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

PBKDF2_ITERATIONS = 310_000
ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "$".join([
        ALGORITHM, str(PBKDF2_ITERATIONS),
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    ])


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$")
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(actual, expected)


def create_token(user_id: int, secret: str, ttl_minutes: int) -> tuple[str, str, datetime]:
    jti = uuid.uuid4().hex
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    token = jwt.encode({"sub": str(user_id), "jti": jti, "exp": expires}, secret, algorithm="HS256")
    return token, jti, expires


def decode_token(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])
