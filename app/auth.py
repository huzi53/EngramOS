import os
import time

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from db import get_conn

router = APIRouter()

JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is required")
ACCESS_TTL_MIN = int(os.environ.get("ACCESS_TTL_MIN", "30"))
REFRESH_TTL_DAYS = int(os.environ.get("REFRESH_TTL_DAYS", "60"))
ALGORITHM = "HS256"


class LoginBody(BaseModel):
    username: str
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


def get_user_by_username(username: str):
    """DB lookup, isolated so test_auth.py can monkeypatch it and stay DB-free."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"id": str(row[0]), "username": row[1], "password_hash": row[2]}


def encode_token(sub: str, token_type: str, ttl_seconds: int, **extra) -> str:
    now = int(time.time())
    payload = {"sub": sub, "type": token_type, "iat": now, "exp": now + ttl_seconds, **extra}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="invalid or expired token")


def require_access(authorization: str = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    payload = decode_token(authorization.removeprefix("Bearer "))
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="not an access token")
    return payload


@router.post("/api/v1/auth/login")
def login(body: LoginBody):
    user = get_user_by_username(body.username)
    if user is None or not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="invalid credentials")
    access = encode_token(user["id"], "access", ACCESS_TTL_MIN * 60, username=user["username"])
    refresh = encode_token(user["id"], "refresh", REFRESH_TTL_DAYS * 24 * 3600, username=user["username"])
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


@router.post("/api/v1/auth/refresh")
def refresh(body: RefreshBody):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="not a refresh token")
    access = encode_token(payload["sub"], "access", ACCESS_TTL_MIN * 60, username=payload.get("username", ""))
    return {"access_token": access, "token_type": "bearer"}
    # ponytail: stateless refresh, no revocation list — rotate JWT_SECRET to invalidate
    # all sessions; add a token table only if multi-device revoke is ever needed.


@router.get("/api/v1/me")
def me(payload: dict = Depends(require_access)):
    return {"id": payload["sub"], "username": payload.get("username", "")}
