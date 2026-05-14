"""
Metrics Collector
-----------------
Background service that runs in the cluster, queries Kubernetes for pod
state, scrapes per-pod /metrics endpoints, and ships aggregated stats to
CloudWatch and S3.

Runs continuously — no HTTP API. Sleeps COLLECTION_INTERVAL_SECONDS
between cycles.

Required IAM permissions on its ServiceAccount (via IRSA):
  - cloudwatch:PutMetricData
  - s3:PutObject, s3:GetObject  (on the metrics bucket)

Required Kubernetes permissions (via Role / RoleBinding):
  - get, list on pods
  - get on pods/metrics (if using metrics.k8s.io)
"""

import io
import os
import csv
import time
import logging
from datetime import datetime, timezone

import boto3
import requests
from kubernetes import client, config
from botocore.exceptions import ClientError

# ---------- Configuration (read from environment) ----------
MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() == "true"
NAMESPACE = os.environ.get("NAMESPACE", "default")
WORKLOAD_LABEL = os.environ.get("WORKLOAD_LABEL", "app=workload-service")
WORKLOAD_PORT = int(os.environ.get("WORKLOAD_PORT", "5000"))
# In MOCK_MODE, we can provide a comma-separated list of IPs or hostnames
STATIC_WORKLOAD_ENDPOINTS = os.environ.get("STATIC_WORKLOAD_ENDPOINTS", "workload:5000")

CLOUDWATCH_NAMESPACE = os.environ.get("CW_NAMESPACE", "IntelligentScheduler")
S3_BUCKET = os.environ.get("S3_BUCKET")              # optional in MOCK_MODE
S3_KEY = os.environ.get("S3_KEY", "metrics/history.csv")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

INTERVAL = int(os.environ.get("COLLECTION_INTERVAL_SECONDS", "30"))

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("metrics-collector")

# ---------- Clients ----------
core_v1 = None
cw = None
s3 = None

if not MOCK_MODE:
    config.load_incluster_config()           # uses the pod's ServiceAccount
    core_v1 = client.CoreV1Api()
    cw = boto3.client("cloudwatch", region_name=AWS_REGION)
    if not S3_BUCKET:
        raise ValueError("S3_BUCKET is required when MOCK_MODE is false")
    s3 = boto3.client("s3", region_name=AWS_REGION)

# Track previous total request count so we can compute rate
_previous_total_requests = 0
_previous_timestamp = None

CSV_HEADER = [
    "timestamp", "pod_count", "total_requests",
    "request_rate_per_sec", "avg_latency_ms",
]


def list_workload_pods():
    """Return running pods of the workload service."""
    if MOCK_MODE:
        # Return a list of "mock" pod-like objects with a status.pod_ip attribute
        from types import SimpleNamespace
        endpoints = STATIC_WORKLOAD_ENDPOINTS.split(",")
        return [SimpleNamespace(status=SimpleNamespace(pod_ip=ep.split(":")[0])) for ep in endpoints]

    pods = core_v1.list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector=WORKLOAD_LABEL,
    )
    return [
        p for p in pods.items
        if p.status.phase == "Running" and p.status.pod_ip
    ]


def scrape_pod_metrics(pod_ip):
    """Hit a single pod's /metrics endpoint."""
    try:
        r = requests.get(
            f"http://{pod_ip}:{WORKLOAD_PORT}/metrics",
            timeout=2,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("Failed to scrape pod %s: %s", pod_ip, e)
        return None


def collect_once():
    """Run a single collection cycle. Return the metrics dict."""
    global _previous_total_requests, _previous_timestamp

    pods = list_workload_pods()
    pod_count = len(pods)

    total_requests = 0
    total_latency_ms = 0
    samples = 0

    for pod in pods:
        m = scrape_pod_metrics(pod.status.pod_ip)
        if m is None:
            continue
        total_requests += m.get("request_count", 0)
        if m.get("request_count", 0) > 0:
            total_latency_ms += m.get("avg_latency_ms", 0)
            samples += 1

    avg_latency = total_latency_ms / samples if samples else 0

    # Compute request rate (delta over time)
    now = time.time()
    if _previous_timestamp is not None:
        delta_t = now - _previous_timestamp
        delta_req = max(0, total_requests - _previous_total_requests)
        request_rate = delta_req / delta_t if delta_t > 0 else 0
    else:
        request_rate = 0

    _previous_total_requests = total_requests
    _previous_timestamp = now

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pod_count": pod_count,
        "total_requests": total_requests,
        "request_rate_per_sec": round(request_rate, 2),
        "avg_latency_ms": round(avg_latency, 2),
    }


def push_to_cloudwatch(metrics):
    """Send custom metrics to CloudWatch."""
    if MOCK_MODE:
        log.info("MOCK_MODE: Skipping CloudWatch push")
        return
    try:
        cw.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "PodCount",
                    "Value": metrics["pod_count"],
                    "Unit": "Count",
                },
                {
                    "MetricName": "RequestRate",
                    "Value": metrics["request_rate_per_sec"],
                    "Unit": "Count/Second",
                },
                {
                    "MetricName": "AvgLatency",
                    "Value": metrics["avg_latency_ms"],
                    "Unit": "Milliseconds",
                },
            ],
        )
    except ClientError as e:
        log.error("CloudWatch put failed: %s", e)


def append_to_s3(metrics):
    """Read existing CSV from S3, append a row, write it back."""
    if MOCK_MODE:
        log.info("MOCK_MODE: Appending to local CSV instead of S3")
        local_path = "history_local.csv"
        file_exists = os.path.isfile(local_path)
        with open(local_path, "a") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(CSV_HEADER)
            writer.writerow([metrics[c] for c in CSV_HEADER])
        return

    # Note: this read-modify-write pattern is fine for a school project and
    # a single collector pod. In production you'd use Kinesis Firehose or
    # an append-friendly format like Parquet partitions.
    try:
        # Try to fetch existing CSV
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
            existing = obj["Body"].read().decode("utf-8")
        except s3.exceptions.NoSuchKey:
            existing = ""

        out = io.StringIO()
        writer = csv.writer(out)
        if not existing:
            writer.writerow(CSV_HEADER)
        else:
            out.write(existing)
            if not existing.endswith("\n"):
                out.write("\n")
        writer.writerow([metrics[c] for c in CSV_HEADER])

        s3.put_object(
            Bucket=S3_BUCKET,
            Key=S3_KEY,
            Body=out.getvalue().encode("utf-8"),
            ContentType="text/csv",
        )
    except ClientError as e:
        log.error("S3 put failed: %s", e)


def main():
    log.info("Metrics Collector starting. Interval=%ss bucket=%s",
             INTERVAL, S3_BUCKET)

    while True:
        try:
            metrics = collect_once()
            log.info("Collected: %s", metrics)
            push_to_cloudwatch(metrics)
            append_to_s3(metrics)
        except Exception as e:
            log.exception("Collection cycle failed: %s", e)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
