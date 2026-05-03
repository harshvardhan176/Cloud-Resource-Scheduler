"""
Workload Service
----------------
The "fake" application that gets scaled. Simulates real work by sleeping
for a configurable duration. Exposes Prometheus-style metrics so the
Metrics Collector can scrape per-pod stats.

Endpoints:
  GET /process?duration_ms=200   -> simulates work, returns 200 OK
  GET /health                    -> liveness probe for Kubernetes
  GET /ready                     -> readiness probe for Kubernetes
  GET /metrics                   -> per-pod metrics for the collector
"""

import os
import time
import socket
import threading
from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory counters. Each pod has its own copy — that's why the collector
# aggregates across all pods.
START_TIME = time.time()
_lock = threading.Lock()
STATS = {
    "request_count": 0,
    "total_processing_ms": 0,
    "errors": 0,
}

POD_NAME = os.environ.get("HOSTNAME", socket.gethostname())


@app.route("/process")
def process():
    """Simulate doing real work."""
    try:
        duration_ms = int(request.args.get("duration_ms", 200))
        # Cap duration so a misbehaving client can't stall the pod
        duration_ms = max(10, min(duration_ms, 2000))
    except ValueError:
        with _lock:
            STATS["errors"] += 1
        return jsonify({"error": "duration_ms must be an integer"}), 400

    time.sleep(duration_ms / 1000.0)

    with _lock:
        STATS["request_count"] += 1
        STATS["total_processing_ms"] += duration_ms

    return jsonify({
        "status": "ok",
        "pod": POD_NAME,
        "processed_in_ms": duration_ms,
    })


@app.route("/health")
def health():
    """Kubernetes liveness probe — is the process alive?"""
    return jsonify({"status": "healthy", "pod": POD_NAME}), 200


@app.route("/ready")
def ready():
    """Kubernetes readiness probe — am I ready to serve traffic?"""
    return jsonify({"status": "ready", "pod": POD_NAME}), 200


@app.route("/metrics")
def metrics():
    """Per-pod metrics in JSON. The Metrics Collector scrapes this."""
    with _lock:
        snapshot = dict(STATS)

    uptime = time.time() - START_TIME
    avg_latency = (
        snapshot["total_processing_ms"] / snapshot["request_count"]
        if snapshot["request_count"] > 0 else 0
    )

    return jsonify({
        "pod": POD_NAME,
        "uptime_seconds": round(uptime, 2),
        "request_count": snapshot["request_count"],
        "errors": snapshot["errors"],
        "avg_latency_ms": round(avg_latency, 2),
        "rps": round(snapshot["request_count"] / uptime, 2) if uptime > 0 else 0,
    })


if __name__ == "__main__":
    # 0.0.0.0 is required so the container accepts external connections
    app.run(host="0.0.0.0", port=5000)
