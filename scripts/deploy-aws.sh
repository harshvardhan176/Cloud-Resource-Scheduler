#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  CloudBrain · End-to-end AWS deployment (eksctl-based)
#
#  Usage:  ./scripts/deploy-aws.sh
#
#  What it does:
#    1.  Pre-flight checks
#    2.  Create supporting AWS resources (DynamoDB, S3, SNS, CW, Lambda)
#    3.  Provision EKS cluster via eksctl
#    4.  Install AWS Load Balancer Controller + metrics-server
#    5.  Create ECR repositories + build/push 8 images
#    6.  Patch + apply Kubernetes manifests
#    7.  Wait for pods to be ready
#    8.  Print public ALB URL
#
#  Time:   ~45–60 minutes
#  Tear down with: ./scripts/teardown-aws.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ENV="dev"
CLUSTER="cloudbrain"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
step()  { echo -e "\n${GREEN}▸ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $1${NC}"; }
die()   { echo -e "${RED}✗ $1${NC}" >&2; exit 1; }

# ── Step 1: Pre-flight ────────────────────────────────────
step "1/8 · Pre-flight checks"
command -v aws     >/dev/null || die "aws CLI not installed"
command -v eksctl  >/dev/null || die "eksctl not installed — run: brew install eksctl"
command -v kubectl >/dev/null || die "kubectl not installed"
command -v docker  >/dev/null || die "docker not installed"
command -v jq      >/dev/null || die "jq not installed"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) \
  || die "AWS credentials not configured — run 'aws configure'"
echo "  Account : $ACCOUNT"
echo "  Region  : $REGION"
echo "  Cluster : $CLUSTER"

# ── Step 2: Supporting AWS resources ──────────────────────
step "2/8 · Creating supporting AWS resources (DynamoDB, S3, SNS, CloudTrail, Lambda)"
bash "$ROOT/aws-infrastructure/scripts/create-resources.sh"
source /tmp/cb-outputs.env

# ── Step 3: EKS cluster via eksctl ────────────────────────
step "3/8 · Provisioning EKS cluster via eksctl (15–20 min)"
if eksctl get cluster --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1; then
  echo "  ✓ cluster already exists — skipping"
else
  eksctl create cluster -f aws-infrastructure/eksctl/cluster.yaml
fi

# Update kubeconfig
aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER"
kubectl get nodes

# ── Step 4: Cluster add-ons ───────────────────────────────
step "4/8 · Installing AWS Load Balancer Controller + metrics-server"

# Install cert-manager first (LBC dependency)
kubectl apply --validate=false -f \
  https://github.com/jetstack/cert-manager/releases/download/v1.13.1/cert-manager.yaml
echo "  waiting for cert-manager..."
kubectl -n cert-manager wait --for=condition=available --timeout=240s deployment --all || \
  warn "cert-manager not fully ready — continuing"

# AWS Load Balancer Controller via kubectl
curl -fsSL -o /tmp/v2_7_2_full.yaml \
  https://github.com/kubernetes-sigs/aws-load-balancer-controller/releases/download/v2.7.2/v2_7_2_full.yaml
sed -i.bak "s|your-cluster-name|${CLUSTER}|g" /tmp/v2_7_2_full.yaml
kubectl apply -f /tmp/v2_7_2_full.yaml || true

# Metrics server (for kubectl top + HPAs)
kubectl apply -f \
  https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

echo "  waiting 30 s for controllers to settle..."
sleep 30

# ── Step 5: ECR + image push ──────────────────────────────
step "5/8 · Creating ECR repos + building 8 images (15–25 min)"

REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
SERVICES=(api-gateway auth-service ml-prediction-service rl-scheduler-service
          executor-service observability-service dashboard-backend-service frontend)

for svc in "${SERVICES[@]}"; do
  aws ecr describe-repositories --repository-names "cloudbrain/$svc" --region "$REGION" >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name "cloudbrain/$svc" --region "$REGION" \
       --image-scanning-configuration scanOnPush=true >/dev/null
done
echo "  ✓ ECR repos ready"

# Docker login to ECR
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

# Build & push
for svc in api-gateway auth-service ml-prediction-service rl-scheduler-service \
           executor-service observability-service dashboard-backend-service; do
  echo "  → building $svc"
  docker build --platform linux/amd64 \
    -f "microservices/$svc/Dockerfile" \
    -t "$REGISTRY/cloudbrain/$svc:1.0.0" "$ROOT"
  docker push "$REGISTRY/cloudbrain/$svc:1.0.0"
done

echo "  → building frontend"
docker build --platform linux/amd64 \
  -f frontend/Dockerfile \
  -t "$REGISTRY/cloudbrain/frontend:1.0.0" "$ROOT/frontend"
docker push "$REGISTRY/cloudbrain/frontend:1.0.0"

# ── Step 6: Patch + apply manifests ───────────────────────
step "6/8 · Deploying CloudBrain to EKS"

JWT_SECRET="$(openssl rand -hex 32)"
mkdir -p /tmp/cb-manifests

# Patch deployments image refs
sed "s|REGISTRY|${REGISTRY}|g" kubernetes/base/deployments.yaml > /tmp/cb-manifests/deployments.yaml

# Patch secrets with real values
sed -e "s|REPLACE-ME-WITH-LONG-RANDOM|${JWT_SECRET}|g" \
    -e "s|SNS_ALERTS_TOPIC_ARN: \"\"|SNS_ALERTS_TOPIC_ARN: \"${CB_SNS_TOPIC_ARN}\"|" \
    kubernetes/base/secrets.yaml > /tmp/cb-manifests/secrets.yaml

# Patch configmap with the real DynamoDB table names + S3 bucket
sed -e "s|cloudbrain-dev-users|${CB_DYNAMODB_USERS}|g" \
    -e "s|cloudbrain-dev-decisions|${CB_DYNAMODB_DECISIONS}|g" \
    -e "s|cloudbrain-dev-audit|${CB_DYNAMODB_AUDIT}|g" \
    kubernetes/base/configmap.yaml > /tmp/cb-manifests/configmap.yaml

# Apply in order
kubectl apply -f kubernetes/base/namespace.yaml
kubectl apply -f /tmp/cb-manifests/configmap.yaml
kubectl apply -f /tmp/cb-manifests/secrets.yaml
kubectl apply -f kubernetes/base/prometheus.yaml
kubectl apply -f /tmp/cb-manifests/deployments.yaml
kubectl apply -f kubernetes/base/services.yaml
kubectl apply -f kubernetes/base/traffic-generator.yaml
kubectl apply -f kubernetes/base/ingress.yaml

# ── Step 7: Wait for rollout ─────────────────────────────
step "7/8 · Waiting for pods to be ready (3–5 min)"
for svc in api-gateway auth-service ml-prediction-service rl-scheduler-service \
           executor-service observability-service dashboard-backend-service \
           prometheus frontend; do
  kubectl -n cloudbrain rollout status deploy/$svc --timeout=180s 2>/dev/null \
    || warn "$svc not yet ready"
done

# ── Step 8: Public URL ───────────────────────────────────
step "8/8 · Fetching public URL"
echo "  Waiting up to 4 minutes for ALB to provision..."
ALB=""
for i in $(seq 1 24); do
  ALB=$(kubectl -n cloudbrain get ingress cloudbrain-ingress \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
  [[ -n "$ALB" ]] && break
  sleep 10
done

echo
echo "════════════════════════════════════════════════════════"
if [[ -n "$ALB" ]]; then
  echo -e "${GREEN}✓ CloudBrain is LIVE on AWS${NC}"
  echo
  echo "   URL:         http://${ALB}"
  echo "   Login:       admin@cloudbrain.dev / admin123"
  echo "   Cluster:     ${CLUSTER}"
  echo
  echo "   Traffic generator runs every minute — give it 60-90 seconds"
  echo "   for the dashboard to populate with live metrics."
else
  warn "ALB not yet ready — try in a minute:"
  echo "  kubectl -n cloudbrain get ingress cloudbrain-ingress"
fi
echo
echo "   When done: ./scripts/teardown-aws.sh"
echo "════════════════════════════════════════════════════════"
