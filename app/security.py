import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def _encode(claims: dict) -> str:
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    return _encode({"sub": str(user_id), "role": role, "type": "access", "iat": now,
                    "exp": now + timedelta(minutes=settings.access_token_minutes)})


def create_refresh_token(user_id: int, jti: str, family_id: str) -> str:
    now = datetime.now(timezone.utc)
    return _encode({"sub": str(user_id), "jti": jti, "fam": family_id, "type": "refresh",
                    "iat": now, "exp": now + timedelta(days=settings.refresh_token_days)})


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def new_id() -> str:
    return uuid.uuid4().hex