"""
Forecast Client
---------------
Thin HTTP wrapper around the SageMaker DeepAR endpoint.

Endpoints:
  POST /forecast   -> returns predicted request rate over horizon
  GET  /health     -> liveness
  GET  /ready      -> checks SageMaker endpoint reachability

Required IAM permissions on its ServiceAccount (via IRSA):
  - sagemaker:InvokeEndpoint  (on the specific endpoint)
  - cloudwatch:GetMetricData
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta, timezone

import boto3
from flask import Flask, request, jsonify

# ---------- Configuration ----------
SAGEMAKER_ENDPOINT = os.environ["SAGEMAKER_ENDPOINT"]      # required
CW_NAMESPACE = os.environ.get("CW_NAMESPACE", "IntelligentScheduler")
METRIC_NAME = os.environ.get("METRIC_NAME", "RequestRate")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
HISTORY_MINUTES = int(os.environ.get("HISTORY_MINUTES", "60"))
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "60"))

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("forecast-client")

# ---------- Clients ----------
app = Flask(__name__)
sm_runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION)
cw = boto3.client("cloudwatch", region_name=AWS_REGION)

# Simple in-memory cache so we don't hammer SageMaker on every Lambda call
_cache = {"timestamp": 0, "data": None}


def get_recent_history():
    """Pull the last HISTORY_MINUTES of RequestRate from CloudWatch."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=HISTORY_MINUTES)

    response = cw.get_metric_statistics(
        Namespace=CW_NAMESPACE,
        MetricName=METRIC_NAME,
        StartTime=start,
        EndTime=end,
        Period=60,                # 1-minute granularity
        Statistics=["Average"],
    )

    # CloudWatch returns datapoints in arbitrary order — sort by timestamp
    points = sorted(response["Datapoints"], key=lambda p: p["Timestamp"])
    values = [p["Average"] for p in points]

    if not values:
        # If there's no history yet, fall back to a flat low value
        log.warning("No CloudWatch history yet; using fallback")
        values = [10.0] * 30

    # DeepAR needs a start timestamp aligned to its frequency
    start_ts = points[0]["Timestamp"] if points else start
    return start_ts, values


def call_sagemaker(start_ts, history, horizon):
    """Invoke the DeepAR endpoint."""
    payload = {
        "instances": [{
            "start": start_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "target": history,
        }],
        "configuration": {
            "num_samples": 50,
            "output_types": ["mean", "quantiles"],
            "quantiles": ["0.5", "0.9"],
        },
    }

    response = sm_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="application/json",
        Body=json.dumps(payload),
    )

    result = json.loads(response["Body"].read())
    predictions = result["predictions"][0]
    mean = predictions["mean"][:horizon]
    p90 = predictions.get("quantiles", {}).get("0.9", mean)[:horizon]
    return mean, p90


@app.route("/forecast", methods=["POST"])
def forecast():
    body = request.get_json(silent=True) or {}
    horizon = int(body.get("horizon_minutes", 15))
    horizon = max(1, min(horizon, 60))

    # Serve from cache if fresh
    if (_cache["data"] is not None
            and time.time() - _cache["timestamp"] < CACHE_TTL_SECONDS
            and _cache["data"]["horizon"] >= horizon):
        cached = _cache["data"]
        log.info("Cache hit for horizon=%s", horizon)
        return jsonify({
            "predicted_request_rate": cached["mean"][horizon - 1],
            "predicted_p90": cached["p90"][horizon - 1],
            "horizon_minutes": horizon,
            "cached": True,
        })

    try:
        start_ts, history = get_recent_history()
        mean, p90 = call_sagemaker(start_ts, history, horizon)

        _cache["data"] = {"mean": mean, "p90": p90, "horizon": horizon}
        _cache["timestamp"] = time.time()

        return jsonify({
            "predicted_request_rate": round(mean[horizon - 1], 2),
            "predicted_p90": round(p90[horizon - 1], 2),
            "horizon_minutes": horizon,
            "history_length": len(history),
            "cached": False,
        })
    except Exception as e:
        log.exception("Forecast failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/ready")
def ready():
    """Confirm we can reach SageMaker."""
    try:
        sm = boto3.client("sagemaker", region_name=AWS_REGION)
        info = sm.describe_endpoint(EndpointName=SAGEMAKER_ENDPOINT)
        if info["EndpointStatus"] == "InService":
            return jsonify({"status": "ready"}), 200
        return jsonify({
            "status": "not_ready",
            "endpoint_status": info["EndpointStatus"],
        }), 503
    except Exception as e:
        return jsonify({"status": "not_ready", "error": str(e)}), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
