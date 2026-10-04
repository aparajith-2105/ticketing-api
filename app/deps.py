import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .enums import Role
from .errors import ApiError
from .models import User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise ApiError(401, "NOT_AUTHENTICATED", "Missing bearer token",
                       headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_token(creds.credentials)
        if claims.get("type") != "access":
            raise ValueError("wrong token type")
        user = db.get(User, int(claims["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        raise ApiError(401, "INVALID_TOKEN", "Invalid or expired token",
                       headers={"WWW-Authenticate": "Bearer"})
    if user is None:
        raise ApiError(401, "INVALID_TOKEN", "User no longer exists")
    return user


def require_role(*roles: Role):
    allowed = {r.value for r in roles}

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise ApiError(403, "FORBIDDEN", "Your role is not allowed to do this")
        return user

    return checker