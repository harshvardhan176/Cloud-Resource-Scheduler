#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Tear down all the supporting AWS resources create-resources.sh created.
#  (eksctl handles cluster + VPC + nodegroup deletion separately.)
# ─────────────────────────────────────────────────────────────
set -uo pipefail   # NOT -e — keep going even if some resources are missing

REGION="${AWS_REGION:-us-east-1}"
ENV="dev"
PREFIX="cloudbrain-${ENV}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

echo "▸ Deleting DynamoDB tables..."
for t in users decisions audit; do
  aws dynamodb delete-table --table-name "${PREFIX}-${t}" --region "$REGION" >/dev/null 2>&1 \
    && echo "  ✓ ${PREFIX}-${t}" || echo "  - ${PREFIX}-${t} (not found)"
done

echo
echo "▸ Emptying + deleting S3 buckets..."
for b in models logs-archive cloudtrail; do
  BUCKET="${PREFIX}-${b}-${ACCOUNT}"
  if aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null; then
    aws s3 rm "s3://$BUCKET" --recursive --region "$REGION" >/dev/null 2>&1 || true
    # Delete all versions if versioning was enabled
    aws s3api delete-objects --bucket "$BUCKET" \
      --delete "$(aws s3api list-object-versions --bucket "$BUCKET" \
                  --output=json --query='{Objects: Versions[].{Key:Key,VersionId:VersionId}}' 2>/dev/null)" \
      --region "$REGION" >/dev/null 2>&1 || true
    aws s3api delete-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null \
      && echo "  ✓ $BUCKET" || echo "  - $BUCKET (could not delete)"
  else
    echo "  - $BUCKET (not found)"
  fi
done

echo
echo "▸ Deleting SNS topic..."
SNS_ARN="arn:aws:sns:${REGION}:${ACCOUNT}:${PREFIX}-alerts"
aws sns delete-topic --topic-arn "$SNS_ARN" --region "$REGION" 2>/dev/null \
  && echo "  ✓ deleted" || echo "  - not found"

echo
echo "▸ Deleting CloudTrail..."
aws cloudtrail delete-trail --name "${PREFIX}-trail" --region "$REGION" 2>/dev/null \
  && echo "  ✓ deleted" || echo "  - not found"

echo
echo "▸ Deleting Lambda..."
aws lambda delete-function --function-name "${PREFIX}-log-archiver" --region "$REGION" 2>/dev/null \
  && echo "  ✓ deleted" || echo "  - not found"

echo
echo "▸ Deleting Lambda IAM role..."
aws iam delete-role-policy --role-name "${PREFIX}-lambda-role" --policy-name LogArchiver 2>/dev/null
aws iam detach-role-policy --role-name "${PREFIX}-lambda-role" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null
aws iam delete-role --role-name "${PREFIX}-lambda-role" 2>/dev/null \
  && echo "  ✓ deleted" || echo "  - not found"

echo
echo "▸ Deleting CloudWatch log group..."
aws logs delete-log-group --log-group-name "/cloudbrain/${ENV}" --region "$REGION" 2>/dev/null \
  && echo "  ✓ deleted" || echo "  - not found"

echo
echo "════════════════════════════════════════════════════════"
echo "✓ Supporting AWS resources deleted."
echo "  Cluster + VPC still alive — run: eksctl delete cluster -f aws-infrastructure/eksctl/cluster.yaml"
echo "════════════════════════════════════════════════════════"
