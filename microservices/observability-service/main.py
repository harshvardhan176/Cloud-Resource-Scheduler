"""
Observability Service — port 8007.

Merges what would have been three separate services:
  • Log ingestion → CloudWatch Logs (real)
  • Notifications  → SNS publish (real)
  • In-memory ring buffer for fast dashboard queries

Endpoints:
  POST /observe/log    — ingest a structured log event
  POST /observe/notify — publish an alert via SNS
  GET  /observe/logs   — recent events (ring buffer)
"""
from __future__ import annotations
import json
import logging
import time
import uuid
from collections import deque
from typing import Deque, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field

from backend.aws import get_cloudwatch_logs, get_sns
from backend.config import get_settings

logger = logging.getLogger("observe")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s : %(message)s")

settings = get_settings()
LOG_GROUP = f"/cloudbrain/{settings.environment}"
LOG_STREAM = "application"

LOG_EVENTS = Counter("observe_logs_total", "Log events ingested", ["level"])
NOTIFICATIONS = Counter("observe_notifications_total", "Notifications", ["channel", "outcome"])

# In-memory ring buffer
_RING: Deque[dict] = deque(maxlen=2000)

app = FastAPI(title="CloudBrain · Observability", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class LogEvent(BaseModel):
    service: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    message: str
    ts: float = Field(default_factory=time.time)
    fields: dict = Field(default_factory=dict)


class Notification(BaseModel):
    subject: str
    body: str
    severity: Literal["info", "warning", "critical"] = "info"
    source: str = "cloudbrain"


@app.on_event("startup")
def _startup():
    """Ensure CloudWatch log group + stream exist."""
    try:
        logs = get_cloudwatch_logs()
        try:
            logs.create_log_group(logGroupName=LOG_GROUP)
        except logs.exceptions.ResourceAlreadyExistsException:
            pass
        try:
            logs.create_log_stream(logGroupName=LOG_GROUP, logStreamName=LOG_STREAM)
        except logs.exceptions.ResourceAlreadyExistsException:
            pass
        logger.info("CloudWatch log group ready: %s", LOG_GROUP)
    except Exception as e:
        logger.debug("CloudWatch unavailable (continuing): %s", e)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "observability",
            "log_group": LOG_GROUP, "ring_size": len(_RING)}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/observe/log")
async def ingest_log(event: LogEvent):
    # Store in ring buffer
    record = event.model_dump()
    record["event_id"] = uuid.uuid4().hex[:12]
    _RING.appendleft(record)
    LOG_EVENTS.labels(event.level).inc()

    # Forward to CloudWatch Logs (best-effort)
    try:
        get_cloudwatch_logs().put_log_events(
            logGroupName=LOG_GROUP,
            logStreamName=LOG_STREAM,
            logEvents=[{
                "timestamp": int(event.ts * 1000),
                "message": json.dumps(record),
            }],
        )
        sink = "cloudwatch"
    except Exception as e:
        logger.debug("cloudwatch put_log_events failed: %s", e)
        sink = "ring-only"

    return {"ok": True, "event_id": record["event_id"], "sink": sink}


@app.get("/observe/logs")
async def recent_logs(limit: int = 100, level: Optional[str] = None,
                      service: Optional[str] = None):
    items = list(_RING)
    if level:
        items = [e for e in items if e.get("level") == level]
    if service:
        items = [e for e in items if e.get("service") == service]
    return {"items": items[:limit]}


@app.post("/observe/notify")
async def notify(n: Notification):
    if not settings.sns_alerts_topic_arn:
        NOTIFICATIONS.labels("sns", "simulated").inc()
        return {"ok": True, "channel": "sns", "outcome": "simulated",
                "reason": "SNS_ALERTS_TOPIC_ARN not configured"}

    try:
        get_sns().publish(
            TopicArn=settings.sns_alerts_topic_arn,
            Subject=f"[{n.severity.upper()}] {n.subject}"[:99],
            Message=n.body,
            MessageAttributes={
                "severity": {"DataType": "String", "StringValue": n.severity},
                "source":   {"DataType": "String", "StringValue": n.source},
            },
        )
        NOTIFICATIONS.labels("sns", "sent").inc()
        return {"ok": True, "channel": "sns", "outcome": "sent"}
    except Exception as e:
        NOTIFICATIONS.labels("sns", "failed").inc()
        raise HTTPException(502, f"SNS publish failed: {e}")
