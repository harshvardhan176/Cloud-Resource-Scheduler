"""
RL Scheduler Service — port 8004.

Receives a 7-dim observation, returns a discrete action (one of 6).
Persists every decision to DynamoDB (table: cloudbrain-decisions) so
the dashboard can show real history.
"""
from __future__ import annotations
import logging
import time
import uuid
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from backend.aws import get_dynamodb
from backend.config import get_settings
from rl_engine.agent import ACTIONS, agent_metadata, policy

logger = logging.getLogger("rl")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s : %(message)s")

settings = get_settings()

DECISIONS = Counter("rl_decisions_total", "RL decisions", ["action"])
LATENCY   = Histogram("rl_decision_seconds", "Decision latency",
                      buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5))

app = FastAPI(title="CloudBrain · RL Scheduler", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_table_cache = None
def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = get_dynamodb().Table(settings.dynamodb_decisions_table)
    return _table_cache


class Observation(BaseModel):
    cpu_util:         float = Field(..., ge=0, le=1)
    mem_util:         float = Field(..., ge=0, le=1)
    queue_len:        float = Field(..., ge=0, le=1)
    active_users:     float = Field(..., ge=0, le=1)
    latency_p95:      float = Field(..., ge=0, le=1)
    pod_count:        float = Field(..., ge=0, le=1)
    forecast_cpu_t60: float = Field(..., ge=0, le=1)


class DecisionResponse(BaseModel):
    decision_id: str
    action_id: int
    action: str
    confidence: float
    rationale: str
    served_at: float


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "rl-scheduler", **agent_metadata()}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/rl/agent")
async def agent():
    return agent_metadata()


@app.get("/rl/action-space")
async def action_space():
    return {"n": len(ACTIONS), "actions": [{"id": i, "name": n} for i, n in enumerate(ACTIONS)]}


@app.post("/rl/decide", response_model=DecisionResponse)
async def decide(obs: Observation):
    with LATENCY.time():
        d = policy([
            obs.cpu_util, obs.mem_util, obs.queue_len, obs.active_users,
            obs.latency_p95, obs.pod_count, obs.forecast_cpu_t60,
        ])

    DECISIONS.labels(d.action).inc()

    decision_id = uuid.uuid4().hex[:12]
    served_at = time.time()

    # Persist to DynamoDB (best-effort)
    try:
        _table().put_item(Item={
            "metric": "cpu",                          # partition key
            "ts": Decimal(str(round(served_at, 3))),  # sort key
            "decision_id": decision_id,
            "action": d.action,
            "action_id": d.action_id,
            "confidence": Decimal(str(d.confidence)),
            "rationale": d.rationale,
            "obs": {
                "cpu":      Decimal(str(round(obs.cpu_util, 4))),
                "mem":      Decimal(str(round(obs.mem_util, 4))),
                "queue":    Decimal(str(round(obs.queue_len, 4))),
                "users":    Decimal(str(round(obs.active_users, 4))),
                "latency":  Decimal(str(round(obs.latency_p95, 4))),
                "pods":     Decimal(str(round(obs.pod_count, 4))),
                "forecast": Decimal(str(round(obs.forecast_cpu_t60, 4))),
            },
        })
    except Exception as e:
        logger.debug("dynamodb put failed (continuing): %s", e)

    return DecisionResponse(
        decision_id=decision_id,
        action_id=d.action_id,
        action=d.action,
        confidence=d.confidence,
        rationale=d.rationale,
        served_at=served_at,
    )


@app.get("/rl/history")
async def history(limit: int = 50):
    """Return recent decisions from DynamoDB."""
    try:
        r = _table().query(
            KeyConditionExpression="metric = :m",
            ExpressionAttributeValues={":m": "cpu"},
            ScanIndexForward=False,  # newest first
            Limit=min(max(limit, 1), 100),
        )
        items = []
        for it in r.get("Items", []):
            items.append({
                "decision_id": it.get("decision_id"),
                "action": it.get("action"),
                "confidence": float(it.get("confidence", 0)),
                "rationale": it.get("rationale", ""),
                "ts": float(it.get("ts", 0)),
                "obs": {k: float(v) for k, v in it.get("obs", {}).items()},
            })
        return {"items": items}
    except Exception as e:
        logger.debug("dynamodb query failed: %s", e)
        return {"items": [], "error": str(e)}
