#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  CloudBrain · Local Kubernetes deployment
#
#  Uses Docker Desktop's built-in Kubernetes — same manifests as AWS,
#  just running on your laptop. No cloud cost.
#
#  PREREQUISITE: In Docker Desktop, go to
#     Settings → Kubernetes → Enable Kubernetes  → Apply & Restart
#
#  Usage:  ./scripts/deploy-local.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
step() { echo -e "\n${GREEN}▸ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
die()  { echo -e "${RED}✗ $1${NC}" >&2; exit 1; }

# ── Pre-flight ────────────────────────────────────────────
step "1/5 · Pre-flight"
command -v docker  >/dev/null || die "docker not installed"
command -v kubectl >/dev/null || die "kubectl not installed"

# Switch kubectl context to docker-desktop
if ! kubectl config get-contexts -o name | grep -q '^docker-desktop$'; then
  die "docker-desktop context not found. Enable Kubernetes in Docker Desktop:
       Settings → Kubernetes → Enable Kubernetes → Apply & Restart"
fi
kubectl config use-context docker-desktop >/dev/null
echo "  ✓ using kubectl context: docker-desktop"
echo "  ✓ cluster info:"
kubectl cluster-info | head -2

# ── Build images locally ─────────────────────────────────
step "2/5 · Building 8 images locally (~3-5 min after first time)"
SERVICES=(api-gateway auth-service ml-prediction-service rl-scheduler-service
          executor-service observability-service dashboard-backend-service)

for svc in "${SERVICES[@]}"; do
  echo "  → $svc"
  docker build -f "microservices/$svc/Dockerfile" \
    -t "cloudbrain/$svc:1.0.0" "$ROOT" >/dev/null
done

echo "  → frontend"
docker build -f frontend/Dockerfile \
  -t "cloudbrain/frontend:1.0.0" "$ROOT/frontend" >/dev/null

echo "  ✓ all 8 images built (Docker Desktop Kubernetes shares the host's image cache)"

# ── Patch manifests for local ────────────────────────────
step "3/5 · Patching manifests for local cluster"
mkdir -p /tmp/cb-local
# Strip the registry prefix and the imagePullPolicy
sed -e 's|REGISTRY/||g' \
    -e '/image: cloudbrain\//a\
          imagePullPolicy: IfNotPresent' \
    kubernetes/base/deployments.yaml > /tmp/cb-local/deployments.yaml

# Strip the ALB ingress (won't work locally) — we'll port-forward instead
echo "  ✓ manifests patched"

# ── Apply ────────────────────────────────────────────────
step "4/5 · Applying manifests"
kubectl apply -f kubernetes/base/namespace.yaml
kubectl apply -f kubernetes/base/configmap.yaml
kubectl apply -f kubernetes/base/secrets.yaml
kubectl apply -f kubernetes/base/prometheus.yaml
kubectl apply -f /tmp/cb-local/deployments.yaml
kubectl apply -f kubernetes/base/services.yaml
kubectl apply -f kubernetes/base/traffic-generator.yaml

step "5/5 · Waiting for pods to be ready (~60 s)"
for svc in api-gateway auth-service ml-prediction-service rl-scheduler-service \
           executor-service observability-service dashboard-backend-service \
           prometheus frontend; do
  kubectl -n cloudbrain rollout status deploy/$svc --timeout=120s 2>/dev/null \
    || warn "$svc not yet ready"
done

echo
echo "════════════════════════════════════════════════════════"
echo -e "${GREEN}✓ CloudBrain is running on Docker Desktop Kubernetes${NC}"
echo
echo "  To access the dashboard, run in a separate terminal:"
echo "    kubectl port-forward -n cloudbrain svc/frontend 3000:80"
echo
echo "  Then open: http://localhost:3000"
echo "  Login:     admin@cloudbrain.dev / admin123"
echo
echo "  Useful inspection commands:"
echo "    kubectl -n cloudbrain get pods                  # all running"
echo "    kubectl -n cloudbrain logs deploy/api-gateway   # tail logs"
echo "    kubectl -n cloudbrain get cronjobs              # traffic generator + RL driver"
echo
echo "  Tear down with: ./scripts/teardown-local.sh"
echo "════════════════════════════════════════════════════════"
