"""
CloudBrain · Log Archiver Lambda
─────────────────────────────────────────────
Runs on demand or on EventBridge schedule.
Reads recent CloudWatch logs and archives them to S3 as compressed JSON.

This demonstrates AWS Lambda integration in our cloud-resource-scheduler
project.
"""
import gzip
import io
import json
import os
import time

import boto3

LOG_GROUP = os.environ.get("LOG_GROUP", "/cloudbrain/dev")
BUCKET    = os.environ.get("BUCKET", "")

logs = boto3.client("logs")
s3   = boto3.client("s3")


def lambda_handler(event, context):
    # Last hour's logs
    now = int(time.time() * 1000)
    one_hour_ago = now - 3600 * 1000

    try:
        resp = logs.filter_log_events(
            logGroupName=LOG_GROUP,
            startTime=one_hour_ago,
            endTime=now,
            limit=10000,
        )
    except logs.exceptions.ResourceNotFoundException:
        return {"ok": True, "archived": 0, "note": "log group not yet created"}

    events = resp.get("events", [])
    if not events:
        return {"ok": True, "archived": 0}

    # Compress as gzipped NDJSON
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for e in events:
            gz.write((json.dumps({
                "ts": e.get("timestamp"),
                "stream": e.get("logStreamName"),
                "message": e.get("message"),
            }) + "\n").encode("utf-8"))

    key = f"archive/{time.strftime('%Y/%m/%d')}/cloudbrain-{int(time.time())}.ndjson.gz"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/x-ndjson",
        ContentEncoding="gzip",
    )

    return {"ok": True, "archived": len(events), "s3_key": key}
