import os
import time
import requests
import logging

# ---------- Configuration ----------
FORECAST_URL = os.environ.get("FORECAST_URL", "http://forecast-client:5001/forecast")
DECISION_URL = os.environ.get("DECISION_URL", "http://rl-decision:5002/decide")
WORKLOAD_METRICS_URL = os.environ.get("WORKLOAD_METRICS_URL", "http://workload:5000/metrics")

# In a real K8s/AWS env, this would be the K8s API or an Auto Scaling Group
# For local demo, we just track it in memory or log it.
current_pod_count = 1

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("orchestrator")

def get_metrics():
    """Get current state from workload."""
    try:
        # In mock/local mode, we might only have one workload instance
        r = requests.get(WORKLOAD_METRICS_URL, timeout=5)
        r.raise_for_status()
        data = r.json()
        # Mocking CPU based on RPS for the demo
        rps = data.get("rps", 0)
        cpu = min(100, (rps / 50.0) * 100)
        return cpu, rps
    except Exception as e:
        log.error("Failed to get metrics: %s", e)
        return 50.0, 10.0 # Fallbacks

def get_forecast():
    """Get prediction from forecast service."""
    try:
        r = requests.post(FORECAST_URL, json={"horizon_minutes": 15}, timeout=5)
        r.raise_for_status()
        return r.json().get("predicted_request_rate", 0)
    except Exception as e:
        log.error("Failed to get forecast: %s", e)
        return 20.0

def get_decision(cpu, rps, predicted_rps):
    """Get scaling action from RL service."""
    payload = {
        "current_pod_count": current_pod_count,
        "current_cpu_pct": cpu,
        "recent_request_rate": rps,
        "predicted_request_rate": predicted_rps
    }
    try:
        r = requests.post(DECISION_URL, json=payload, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Failed to get decision: %s", e)
        return None

def apply_action(decision):
    global current_pod_count
    if not decision:
        return

    new_count = decision.get("new_pod_count", current_pod_count)
    action = decision.get("action", "stay")

    if new_count != current_pod_count:
        log.info("SCALING ACTION: %s -> %d pods (Action: %s)", current_pod_count, new_count, action)
        current_pod_count = new_count
    else:
        log.info("NO ACTION: Staying at %d pods", current_pod_count)

def main():
    log.info("Local Orchestrator started. Loop interval: 30s")
    while True:
        log.info("--- Starting Scaling Cycle ---")
        cpu, rps = get_metrics()
        log.info("Current State: CPU=%.1f%%, RPS=%.1f", cpu, rps)

        predicted_rps = get_forecast()
        log.info("Forecasted RPS: %.1f", predicted_rps)

        decision = get_decision(cpu, rps, predicted_rps)
        apply_action(decision)

        time.sleep(30)

if __name__ == "__main__":
    main()
