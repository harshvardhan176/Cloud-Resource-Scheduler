"""
API Gateway — port 8000.
Single front door: JWT verification + rate limit + reverse proxy.
"""
from __future__ import annotations
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from backend.auth import verify_token
from backend.config import get_settings

logger = logging.getLogger("api-gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s : %(message)s")

settings = get_settings()

REQUESTS = Counter("gateway_requests_total", "Total requests", ["route", "status"])
LATENCY  = Histogram("gateway_request_seconds", "Request latency",
                     buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))

# Route prefix → downstream service URL
ROUTES = {
    "auth":    settings.auth_service_url,
    "ml":      settings.ml_prediction_service_url,
    "rl":      settings.rl_scheduler_service_url,
    "exec":    settings.executor_service_url,
    "observe": settings.observability_service_url,
}

# Paths that don't require a JWT
PUBLIC_PATHS = {"/healthz", "/metrics", "/auth/login", "/auth/register",
                "/ml/models", "/ml/predict", "/rl/agent", "/rl/action-space",
                "/rl/history", "/exec/history"}


# ─────────── Simple in-memory rate limiter ───────────
class TokenBucket:
    """Per-IP token bucket: 60 requests/sec sustained, 60 burst."""

    def __init__(self, capacity: int = 60, refill_per_sec: float = 1.0) -> None:
        self.capacity = capacity
        self.refill = refill_per_sec
        self.buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        tokens, last = self.buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.refill)
        if tokens >= 1:
            self.buckets[key] = (tokens - 1, now)
            return True
        self.buckets[key] = (tokens, now)
        return False


# ─────────── Lifespan ───────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=10.0, follow_redirects=False)
    app.state.limiter = TokenBucket()
    yield
    await app.state.http.aclose()


app = FastAPI(title="CloudBrain · API Gateway", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─────────── Endpoints ───────────
@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "api-gateway", "env": settings.environment}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.api_route("/{prefix}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(prefix: str, path: str, request: Request):
    """Reverse-proxy /<prefix>/... → ROUTES[prefix]/<prefix>/<path>"""
    full_path = f"/{prefix}/{path}"

    if prefix not in ROUTES:
        raise HTTPException(404, f"unknown service prefix '{prefix}'")

    # Rate limit
    client_ip = request.client.host if request.client else "unknown"
    if not app.state.limiter.allow(client_ip):
        REQUESTS.labels(prefix, "429").inc()
        raise HTTPException(429, "rate limit exceeded")

    # Auth (skip for public paths)
    if full_path not in PUBLIC_PATHS:
        authz = request.headers.get("authorization", "")
        if not authz.lower().startswith("bearer "):
            REQUESTS.labels(prefix, "401").inc()
            raise HTTPException(401, "missing bearer token")
        try:
            verify_token(authz.split(" ", 1)[1])
        except ValueError as e:
            REQUESTS.labels(prefix, "401").inc()
            raise HTTPException(401, str(e))

    # Proxy
    upstream = ROUTES[prefix].rstrip("/") + full_path
    body = await request.body()
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length")}

    with LATENCY.time():
        try:
            r = await app.state.http.request(
                request.method, upstream,
                content=body, headers=headers,
                params=dict(request.query_params),
            )
        except httpx.RequestError as e:
            REQUESTS.labels(prefix, "503").inc()
            raise HTTPException(503, f"upstream unreachable: {e}")

    REQUESTS.labels(prefix, str(r.status_code)).inc()
    return Response(
        content=r.content,
        status_code=r.status_code,
        headers={k: v for k, v in r.headers.items()
                 if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")},
    )
