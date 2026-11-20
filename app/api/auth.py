import os

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def unauthorized(detail="Invalid access token"):
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    if not isinstance(token, str) or not token:
        raise unauthorized("Access token required")
    if not settings.JWT_SECRET:
        raise HTTPException(status_code=503, detail="Authentication unavailable")
    try:
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise unauthorized() from None
    if (
        claims.get("type", "access") != "access"
        or "share_type" in claims
        or not claims.get("user_id")
    ):
        raise unauthorized()
    return str(claims["user_id"])


def get_share_signing_key():
    secret = os.getenv("SHARED_TOKEN_SECRET")
    if not secret or secret == settings.JWT_SECRET:
        raise HTTPException(status_code=503, detail="Sharing unavailable")
    return secret


def check_auth_service(token, path):
    if not token:
        raise unauthorized("Access token required")
    if not settings.AUTH_SERVICE_URL:
        raise HTTPException(status_code=503, detail="Authentication unavailable")
    try:
        response = httpx.get(
            f"{settings.AUTH_SERVICE_URL.rstrip('/')}/auth/{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=3.0,
            trust_env=False,
        )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Authentication unavailable") from None
    if response.status_code in (401, 422):
        raise unauthorized()
    return response


def require_reindex_permission(token: str = Depends(oauth2_scheme)):
    response = check_auth_service(token, "permissions/annotation/reindex")
    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="Re-index permission required")
    if response.status_code != 204:
        raise HTTPException(status_code=503, detail="Authentication unavailable")


def get_verified_email(token: str = Depends(oauth2_scheme)) -> str:
    response = check_auth_service(token, "email/verified")
    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="A verified email is required")
    if response.status_code == 200:
        try:
            email = response.json()["email"]
            if isinstance(email, str) and email:
                return email
        except (ValueError, KeyError, TypeError):
            pass
    raise HTTPException(status_code=503, detail="Authentication unavailable")
