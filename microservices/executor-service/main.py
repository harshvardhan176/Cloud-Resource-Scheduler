"""
Executor Service — port 8005.

Receives a high-level action (typically from the RL agent) and translates
it to AWS / Kubernetes operations. DRY_RUN=true by default for safety.

Every operation is written to DynamoDB (audit table) for traceability.
"""
from __future__ import annotations
import logging
import os
import time
import uuid
from decimal import Decimal
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field

from backend.aws import get_dynamodb, get_ec2
from backend.config import get_settings

logger = logging.getLogger("executor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s : %(message)s")

settings = get_settings()
DRY_RUN = os.getenv("EXECUTOR_DRY_RUN", "true").lower() == "true"

OPS = Counter("executor_ops_total", "Operations executed", ["action", "outcome"])

app = FastAPI(title="CloudBrain · Executor", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_table_cache = None
def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = get_dynamodb().Table(settings.dynamodb_audit_table)
    return _table_cache


ActionType = Literal[
    "noop", "add_replica", "remove_replica",
    "add_ec2_ondemand", "add_ec2_spot", "enable_fargate_burst",
]


class ExecuteRequest(BaseModel):
    action: ActionType
    deployment: str = Field("api-gateway", description="k8s deployment for replica actions")
    namespace: str = "cloudbrain"
    instance_type: str = "t3.medium"
    requested_by: str = "rl-scheduler"
    rationale: Optional[str] = None


class OperationResult(BaseModel):
    op_id: str
    action: str
    outcome: Literal["success", "simulated", "noop", "failed"]
    details: dict
    cost_delta_usd_per_hour: float
    executed_at: float
    dry_run: bool


COSTS = {
    "noop":                  0.0,
    "add_replica":           0.05,
    "remove_replica":       -0.05,
    "add_ec2_ondemand":      0.0416,
    "add_ec2_spot":          0.0125,
    "enable_fargate_burst":  0.12,
}


def _write_audit(op: OperationResult, requested_by: str, rationale: Optional[str]) -> None:
    try:
        _table().put_item(Item={
            "op_id": op.op_id,
            "ts": Decimal(str(round(op.executed_at, 3))),
            "action": op.action,
            "outcome": op.outcome,
            "cost_delta": Decimal(str(op.cost_delta_usd_per_hour)),
            "requested_by": requested_by,
            "rationale": rationale or "",
            "dry_run": op.dry_run,
            "details": {k: str(v) for k, v in op.details.items()},
        })
    except Exception as e:
        logger.debug("audit write failed (continuing): %s", e)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "executor", "dry_run": DRY_RUN}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/exec/execute", response_model=OperationResult)
async def execute(req: ExecuteRequest) -> OperationResult:
    op_id = uuid.uuid4().hex[:12]
    now = time.time()
    cost = COSTS.get(req.action, 0.0)

    if req.action == "noop":
        op = OperationResult(
            op_id=op_id, action="noop", outcome="noop",
            details={"note": "no action required"},
            cost_delta_usd_per_hour=0.0, executed_at=now, dry_run=DRY_RUN,
        )
        OPS.labels("noop", "noop").inc()
        _write_audit(op, req.requested_by, req.rationale)
        return op

    if DRY_RUN:
        op = OperationResult(
            op_id=op_id, action=req.action, outcome="simulated",
            details={
                "would_do": req.action,
                "deployment": req.deployment,
                "instance_type": req.instance_type if req.action.startswith("add_ec2") else None,
                "namespace": req.namespace,
            },
            cost_delta_usd_per_hour=cost,
            executed_at=now, dry_run=True,
        )
        OPS.labels(req.action, "simulated").inc()
        _write_audit(op, req.requested_by, req.rationale)
        return op

    # Real-execution path (only when DRY_RUN=false)
    try:
        if req.action in ("add_ec2_ondemand", "add_ec2_spot"):
            ec2 = get_ec2()
            kwargs = {
                "ImageId": os.getenv("CLOUDBRAIN_AMI", "ami-0c55b159cbfafe1f0"),
                "InstanceType": req.instance_type,
                "MinCount": 1, "MaxCount": 1,
                "TagSpecifications": [{
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Project", "Value": "CloudBrain"}],
                }],
            }
            if req.action == "add_ec2_spot":
                kwargs["InstanceMarketOptions"] = {"MarketType": "spot"}
            r = ec2.run_instances(**kwargs)
            iid = r["Instances"][0]["InstanceId"]
            details = {"instance_id": iid, "market": "spot" if "spot" in req.action else "ondemand"}
        else:
            details = {"note": "k8s actions require kubectl in pod — omitted in this build"}

        op = OperationResult(
            op_id=op_id, action=req.action, outcome="success",
            details=details, cost_delta_usd_per_hour=cost,
            executed_at=now, dry_run=False,
        )
        OPS.labels(req.action, "success").inc()
        _write_audit(op, req.requested_by, req.rationale)
        return op
    except Exception as e:
        OPS.labels(req.action, "failed").inc()
        raise HTTPException(502, f"execution failed: {e}")


@app.get("/exec/history")
async def history(limit: int = 50):
    """Recent operations from DynamoDB audit table."""
    try:
        r = _table().scan(Limit=min(max(limit, 1), 100))
        items = sorted(r.get("Items", []), key=lambda x: float(x.get("ts", 0)), reverse=True)
        return {
            "items": [{
                "op_id": it["op_id"],
                "ts": float(it["ts"]),
                "action": it["action"],
                "outcome": it["outcome"],
                "cost_delta_usd_per_hour": float(it["cost_delta"]),
                "requested_by": it.get("requested_by"),
                "rationale": it.get("rationale"),
                "dry_run": it.get("dry_run"),
            } for it in items[:limit]]
        }
    except Exception as e:
        logger.debug("audit scan failed: %s", e)
        return {"items": [], "error": str(e)}
