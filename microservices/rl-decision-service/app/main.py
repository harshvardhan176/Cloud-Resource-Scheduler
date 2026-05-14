"""
RL Decision Service
-------------------
Loads a trained DQN policy from S3 on startup and exposes a /decide
endpoint that returns scaling actions.

Endpoints:
  POST /decide   -> returns scaling action given current state + forecast
  GET  /health   -> liveness
  GET  /ready    -> ensures the model is loaded
  POST /reload   -> manual model reload (for pushing new policies)

Required IAM permissions on its ServiceAccount (via IRSA):
  - s3:GetObject  (on the model bucket)
"""

import os
import logging
from threading import Lock

import boto3
import numpy as np
from flask import Flask, request, jsonify
from stable_baselines3 import DQN

# ---------- Configuration ----------
MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() == "true"
S3_BUCKET = os.environ.get("MODEL_S3_BUCKET")            # optional in MOCK_MODE
S3_KEY = os.environ.get("MODEL_S3_KEY", "rl-policy.zip")
LOCAL_MODEL_PATH = os.environ.get("LOCAL_MODEL_PATH", "/tmp/rl-policy.zip")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

MIN_PODS = int(os.environ.get("MIN_PODS", "1"))
MAX_PODS = int(os.environ.get("MAX_PODS", "10"))

# Action space: index -> delta in pod count
ACTIONS = {0: -2, 1: -1, 2: 0, 3: +1, 4: +2}

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("rl-decision-service")

# ---------- Clients ----------
app = Flask(__name__)
s3 = None
if not MOCK_MODE:
    s3 = boto3.client("s3", region_name=AWS_REGION)

_model = None
_model_lock = Lock()


def download_and_load_model():
    """Pull the trained model from S3 (or use local path) and load it."""
    global _model

    if os.path.exists(LOCAL_MODEL_PATH):
        log.info("Found local model at %s, loading it...", LOCAL_MODEL_PATH)
    elif not MOCK_MODE:
        if not S3_BUCKET:
            raise ValueError("MODEL_S3_BUCKET is required when MOCK_MODE is false and no local model exists")
        log.info("Downloading model from s3://%s/%s to %s", S3_BUCKET, S3_KEY, LOCAL_MODEL_PATH)
        s3.download_file(S3_BUCKET, S3_KEY, LOCAL_MODEL_PATH)
    else:
        log.warning("No local model found and in MOCK_MODE. Skipping model load.")
        return

    log.info("Loading model into memory from %s", LOCAL_MODEL_PATH)
    with _model_lock:
        _model = DQN.load(LOCAL_MODEL_PATH)
    log.info("Model loaded successfully")


def fallback_decision(state):
    """Rule-based fallback if the model fails to load.

    This protects the demo: even if S3 is misconfigured or the model
    is corrupt, the service still returns sensible decisions.
    """
    current_pods, current_cpu, _, predicted_rate = state[:4]

    # Capacity heuristic: each pod handles ~50 req/s comfortably
    needed_pods = max(MIN_PODS, int(np.ceil(predicted_rate / 50.0)))
    needed_pods = min(needed_pods, MAX_PODS)
    delta = int(needed_pods - current_pods)
    delta = max(-2, min(2, delta))
    return delta, "fallback"


def model_decision(state):
    """Run the trained policy."""
    with _model_lock:
        action_idx, _ = _model.predict(np.array(state), deterministic=True)
    return ACTIONS[int(action_idx)], "rl"


@app.route("/decide", methods=["POST"])
def decide():
    body = request.get_json(silent=True) or {}
    try:
        current_pods = int(body["current_pod_count"])
        current_cpu = float(body["current_cpu_pct"])
        recent_rate = float(body["recent_request_rate"])
        predicted_rate = float(body["predicted_request_rate"])
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"error": f"bad request: {e}"}), 400

    # State must match the order/shape the policy was trained on
    state = [current_pods, current_cpu, recent_rate, predicted_rate]

    if _model is None:
        delta, source = fallback_decision(state)
    else:
        try:
            delta, source = model_decision(state)
        except Exception as e:
            log.exception("Model inference failed; falling back: %s", e)
            delta, source = fallback_decision(state)

    new_count = max(MIN_PODS, min(MAX_PODS, current_pods + delta))
    actual_delta = new_count - current_pods

    if actual_delta > 0:
        action = "scale_up"
    elif actual_delta < 0:
        action = "scale_down"
    else:
        action = "stay"

    log.info(
        "decide pods=%s cpu=%s rate=%s pred=%s -> %s (new=%s, source=%s)",
        current_pods, current_cpu, recent_rate, predicted_rate,
        action, new_count, source,
    )

    return jsonify({
        "action": action,
        "new_pod_count": new_count,
        "delta": actual_delta,
        "source": source,
    })


@app.route("/reload", methods=["POST"])
def reload_model():
    """Pull a freshly trained model from S3 without restarting the pod."""
    try:
        download_and_load_model()
        return jsonify({"status": "reloaded"}), 200
    except Exception as e:
        log.exception("Reload failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/ready")
def ready():
    if _model is None:
        return jsonify({"status": "not_ready", "reason": "model not loaded"}), 503
    return jsonify({"status": "ready"}), 200


# Load the model when the service starts
try:
    download_and_load_model()
except Exception as e:
    # Don't crash — fall back to rule-based decisions and log loudly
    log.exception("Failed to load model at startup; using fallback: %s", e)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
