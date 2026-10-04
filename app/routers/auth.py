from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..errors import ApiError
from ..models import RefreshToken, User
from ..schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from ..security import (create_access_token, create_refresh_token, decode_token,
                        hash_password, new_id, verify_password)
from ..timeutil import utcnow

router = APIRouter(prefix="/auth", tags=["Auth"])


def _issue_tokens(db: Session, user: User, family_id: str | None = None) -> TokenOut:
    family_id = family_id or new_id()
    jti = new_id()
    db.add(RefreshToken(jti=jti, user_id=user.id, family_id=family_id,
                        expires_at=utcnow() + timedelta(days=settings.refresh_token_days)))
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, user.role),
                    refresh_token=create_refresh_token(user.id, jti, family_id),
                    expires_in=settings.access_token_minutes * 60)


@router.post("/register", response_model=UserOut, status_code=201,
             summary="Register an Attendee or Organizer")
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise ApiError(409, "EMAIL_TAKEN", "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(payload.password),
                full_name=payload.full_name.strip(), role=payload.role.value)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two registrations racing on the same email
        db.rollback()
        raise ApiError(409, "EMAIL_TAKEN", "An account with this email already exists")
    return user


@router.post("/login", response_model=TokenOut, summary="Log in and get tokens")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "Incorrect email or password")
    return _issue_tokens(db, user)


@router.post("/refresh", response_model=TokenOut,
             summary="Exchange a refresh token for a new pair (rotation)")
def refresh(payload: RefreshIn, db: Session = Depends(get_db)):
    try:
        claims = decode_token(payload.refresh_token)
        if claims.get("type") != "refresh":
            raise ValueError
        jti = claims["jti"]
    except (jwt.PyJWTError, ValueError, KeyError):
        raise ApiError(401, "INVALID_TOKEN", "Invalid or expired refresh token")

    token = db.get(RefreshToken, jti)
    if token is None:
        raise ApiError(401, "INVALID_TOKEN", "Unknown refresh token")

    # Atomic "use once": only one caller can flip revoked False -> True.
    res = db.execute(update(RefreshToken)
                     .where(RefreshToken.jti == jti, RefreshToken.revoked.is_(False))
                     .values(revoked=True)
                     .execution_options(synchronize_session=False))
    if res.rowcount == 0:
        # Token was already used: assume theft and kill the whole family.
        db.execute(update(RefreshToken).where(RefreshToken.family_id == token.family_id)
                   .values(revoked=True).execution_options(synchronize_session=False))
        db.commit()
        raise ApiError(401, "TOKEN_REUSED",
                       "Refresh token was already used; all sessions in this family revoked")
    db.commit()
    user = db.get(User, token.user_id)
    return _issue_tokens(db, user, token.family_id)


@router.post("/logout", status_code=204, summary="Revoke a refresh token family")
def logout(payload: RefreshIn, db: Session = Depends(get_db)):
    try:
        claims = decode_token(payload.refresh_token)
        family = claims["fam"]
    except (jwt.PyJWTError, KeyError):
        raise ApiError(401, "INVALID_TOKEN", "Invalid refresh token")
    db.execute(update(RefreshToken).where(RefreshToken.family_id == family)
               .values(revoked=True).execution_options(synchronize_session=False))
    db.commit()
    return Response(status_code=204)


@router.get("/me", response_model=UserOut, summary="Current user")
def me(user: User = Depends(get_current_user)):
    return user