#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  CloudBrain · AWS teardown
#  Order matters:
#    1.  Delete Kubernetes Ingress first (so ALB drops cleanly)
#    2.  Delete the namespace
#    3.  eksctl delete cluster  (removes EKS + VPC + node group)
#    4.  Delete supporting resources (DynamoDB, S3, SNS, Lambda)
#    5.  Delete ECR repos
# ─────────────────────────────────────────────────────────────
set -uo pipefail

REGION="${AWS_REGION:-us-east-1}"
CLUSTER="cloudbrain"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; NC='\033[0m'
step() { echo -e "\n${GREEN}▸ $1${NC}"; }

step "1/5 · Delete Kubernetes resources"
kubectl delete -f kubernetes/base/ingress.yaml --ignore-not-found 2>/dev/null
kubectl delete -f kubernetes/base/services.yaml --ignore-not-found 2>/dev/null
kubectl delete -f kubernetes/base/deployments.yaml --ignore-not-found 2>/dev/null
kubectl delete namespace cloudbrain --ignore-not-found 2>/dev/null

echo "  waiting 90 s for ALB to drop..."
sleep 90

step "2/5 · Delete EKS cluster (10–15 min)"
eksctl delete cluster -f aws-infrastructure/eksctl/cluster.yaml --wait 2>&1 | tail -20 || true

step "3/5 · Delete supporting AWS resources"
bash "$ROOT/aws-infrastructure/scripts/delete-resources.sh"

step "4/5 · Delete ECR repositories"
SERVICES=(api-gateway auth-service ml-prediction-service rl-scheduler-service
          executor-service observability-service dashboard-backend-service frontend)
for svc in "${SERVICES[@]}"; do
  aws ecr delete-repository --repository-name "cloudbrain/$svc" --force --region "$REGION" 2>/dev/null \
    && echo "  ✓ ECR $svc deleted" || echo "  - ECR $svc not found"
done

step "5/5 · Done"
echo
echo "═══════════════════════════════════════════════════════════════"
echo -e "${GREEN}✓ Teardown complete. Verify in AWS Billing dashboard tomorrow.${NC}"
echo "═══════════════════════════════════════════════════════════════"
