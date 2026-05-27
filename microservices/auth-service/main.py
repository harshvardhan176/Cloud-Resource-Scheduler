"""
Auth Service — port 8001.

Stores users in DynamoDB (table: cloudbrain-users). Issues JWTs.
Falls back to an in-memory user dict when DynamoDB isn't configured
(local docker-compose dev mode).
"""
from __future__ import annotations
import logging
import os
import time
from typing import Optional

import bcrypt
from fastapi import FastAPI, Form, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel

from backend.auth import create_access_token, verify_token
from backend.aws import get_dynamodb
from backend.config import get_settings

logger = logging.getLogger("auth")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s : %(message)s")

settings = get_settings()


# ── Minimal bcrypt password helpers (no passlib) ──────────
def _hash_password(password: str) -> str:
    """Hash a password with bcrypt. Truncates to 72 bytes (bcrypt's hard limit)."""
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=10)).decode("utf-8")


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored bcrypt hash."""
    try:
        pw = password.encode("utf-8")[:72]
        return bcrypt.checkpw(pw, stored_hash.encode("utf-8"))
    except Exception:
        return False


LOGINS = Counter("auth_logins_total", "Logins", ["outcome"])

# Use DynamoDB if the table exists; otherwise fall back to in-memory.
USE_DYNAMO = os.getenv("USE_DYNAMODB", "auto").lower()

# In-memory seed users for local dev
_SEED = {
    "admin@cloudbrain.dev": {"password_hash": _hash_password("admin123"), "role": "admin"},
    "ops@cloudbrain.dev":   {"password_hash": _hash_password("ops123"),   "role": "operator"},
}

app = FastAPI(title="CloudBrain · Auth Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── DynamoDB helpers ─────────────────────────────────
def _table():
    return get_dynamodb().Table(settings.dynamodb_users_table)


def _dynamo_available() -> bool:
    if USE_DYNAMO == "false":
        return False
    try:
        _table().load()
        return True
    except Exception as e:
        logger.debug("dynamo unavailable: %s — falling back to in-memory", e)
        return False


def _seed_dynamo() -> None:
    """Make sure the seed users exist in DynamoDB."""
    try:
        for email, info in _SEED.items():
            _table().put_item(
                Item={"email": email, "password_hash": info["password_hash"], "role": info["role"]},
                ConditionExpression="attribute_not_exists(email)",
            )
            logger.info("seeded user %s", email)
    except Exception as e:
        if "ConditionalCheckFailed" not in str(e):
            logger.debug("seed skipped: %s", e)


def _get_user(email: str) -> Optional[dict]:
    if _dynamo_available():
        try:
            r = _table().get_item(Key={"email": email})
            return r.get("Item")
        except Exception as e:
            logger.warning("dynamo get_item failed: %s", e)
            return None
    return _SEED.get(email)


def _put_user(email: str, password: str, role: str = "viewer") -> None:
    item = {"email": email, "password_hash": _hash_password(password), "role": role}
    if _dynamo_available():
        _table().put_item(Item=item)
    else:
        _SEED[email] = {"password_hash": item["password_hash"], "role": role}


@app.on_event("startup")
def _startup():
    if _dynamo_available():
        _seed_dynamo()


# ── Schemas ─────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: str
    password: str
    role: str = "viewer"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


# ── Endpoints ───────────────────────────────────────
@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "auth-service",
            "backend": "dynamodb" if _dynamo_available() else "in-memory"}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/auth/login", response_model=TokenResponse)
async def login(username: str = Form(...), password: str = Form(...)):
    user = _get_user(username)
    if not user or not _verify_password(password, user["password_hash"]):
        LOGINS.labels("failed").inc()
        raise HTTPException(401, "invalid credentials")

    LOGINS.labels("success").inc()
    token = create_access_token(sub=username, role=user["role"])
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
        role=user["role"],
    )


@app.post("/auth/register")
async def register(req: RegisterRequest, authorization: str = Header(default="")):
    """Admin-only: register a new user."""
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "admin token required")
    try:
        claims = verify_token(authorization.split(" ", 1)[1])
    except ValueError as e:
        raise HTTPException(401, str(e))
    if claims.get("role") != "admin":
        raise HTTPException(403, "admin only")

    if _get_user(req.email):
        raise HTTPException(409, "user already exists")

    _put_user(req.email, req.password, req.role)
    return {"ok": True, "email": req.email, "role": req.role}


@app.get("/auth/me")
async def me(authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing token")
    try:
        return verify_token(authorization.split(" ", 1)[1])
    except ValueError as e:
        raise HTTPException(401, str(e))
