#!/usr/bin/env bash
# Smoke test — works against local docker compose or the live ALB
set -euo pipefail
BASE="${1:-http://localhost:8000}"
DASH="${2:-http://localhost:8008}"

echo "Target: $BASE"

curl -fsS "$BASE/healthz" >/dev/null && echo "✓ gateway healthy" || { echo "✗ gateway"; exit 1; }

TOKEN=$(curl -fsS -X POST "$BASE/auth/login" \
  -d 'username=admin@cloudbrain.dev&password=admin123' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
[[ -n "$TOKEN" ]] && echo "✓ auth login" || { echo "✗ auth"; exit 1; }

AUTH="-H Authorization:Bearer\ $TOKEN"

curl -fsS $AUTH "$BASE/ml/models" >/dev/null && echo "✓ ml models" || echo "⚠ ml unreachable"
curl -fsS $AUTH "$BASE/rl/agent"  >/dev/null && echo "✓ rl agent"  || echo "⚠ rl unreachable"

curl -fsS $AUTH -X POST "$BASE/ml/predict" \
  -H "Content-Type: application/json" \
  -d '{"history":[0.4,0.42,0.45,0.43,0.48,0.5,0.52,0.49,0.51,0.55],"horizon":10}' \
  >/dev/null && echo "✓ ml predict" || echo "⚠ ml predict failed"

curl -fsS $AUTH -X POST "$BASE/rl/decide" \
  -H "Content-Type: application/json" \
  -d '{"cpu_util":0.82,"mem_util":0.6,"queue_len":0.5,"active_users":0.5,"latency_p95":0.7,"pod_count":0.3,"forecast_cpu_t60":0.85}' \
  >/dev/null && echo "✓ rl decide" || echo "⚠ rl decide failed"

curl -fsS "$DASH/api/services" >/dev/null && echo "✓ dashboard aggregator" || echo "⚠ dashboard"

echo "Smoke test complete."
