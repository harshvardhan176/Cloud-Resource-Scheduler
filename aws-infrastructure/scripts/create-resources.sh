#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  CloudBrain · Create supporting AWS resources
#  (Everything eksctl doesn't create itself: DynamoDB tables,
#   S3 buckets, SNS topic, CloudWatch log group, CloudTrail,
#   Lambda function.)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ENV="dev"
PREFIX="cloudbrain-${ENV}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

echo "▸ Account : $ACCOUNT"
echo "▸ Region  : $REGION"
echo "▸ Prefix  : $PREFIX"

# ── DynamoDB tables ──────────────────────────────────────
create_table() {
  local name=$1 schema=$2
  if aws dynamodb describe-table --table-name "$name" --region "$REGION" >/dev/null 2>&1; then
    echo "  ✓ table $name already exists"
    return
  fi
  echo "  ▸ creating table $name"
  eval "aws dynamodb create-table --table-name $name --region $REGION --billing-mode PAY_PER_REQUEST $schema >/dev/null"
  aws dynamodb wait table-exists --table-name "$name" --region "$REGION"
}

echo
echo "▸ DynamoDB tables"
create_table "${PREFIX}-users" \
  '--attribute-definitions AttributeName=email,AttributeType=S --key-schema AttributeName=email,KeyType=HASH'

create_table "${PREFIX}-decisions" \
  '--attribute-definitions AttributeName=metric,AttributeType=S AttributeName=ts,AttributeType=N --key-schema AttributeName=metric,KeyType=HASH AttributeName=ts,KeyType=RANGE'

create_table "${PREFIX}-audit" \
  '--attribute-definitions AttributeName=op_id,AttributeType=S --key-schema AttributeName=op_id,KeyType=HASH'

# ── S3 buckets ──────────────────────────────────────────
create_bucket() {
  local name=$1
  if aws s3api head-bucket --bucket "$name" --region "$REGION" 2>/dev/null; then
    echo "  ✓ bucket $name already exists"
    return
  fi
  echo "  ▸ creating bucket $name"
  if [[ "$REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$name" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$name" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  aws s3api put-bucket-versioning --bucket "$name" \
    --versioning-configuration Status=Enabled >/dev/null
}

echo
echo "▸ S3 buckets"
MODELS_BUCKET="${PREFIX}-models-${ACCOUNT}"
LOGS_BUCKET="${PREFIX}-logs-archive-${ACCOUNT}"
TRAIL_BUCKET="${PREFIX}-cloudtrail-${ACCOUNT}"
create_bucket "$MODELS_BUCKET"
create_bucket "$LOGS_BUCKET"
create_bucket "$TRAIL_BUCKET"

# ── SNS topic ───────────────────────────────────────────
echo
echo "▸ SNS topic"
SNS_ARN=$(aws sns create-topic --name "${PREFIX}-alerts" --region "$REGION" \
  --query 'TopicArn' --output text)
echo "  ✓ $SNS_ARN"

# ── CloudWatch log group ────────────────────────────────
echo
echo "▸ CloudWatch log group"
LOG_GROUP="/cloudbrain/${ENV}"
if ! aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --region "$REGION" \
    --query "logGroups[?logGroupName=='$LOG_GROUP'] | length(@)" --output text | grep -q '^1$'; then
  aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$REGION"
  aws logs put-retention-policy --log-group-name "$LOG_GROUP" --retention-in-days 7 --region "$REGION"
  echo "  ✓ created"
else
  echo "  ✓ already exists"
fi

# ── CloudTrail (best-effort — skip on failure since it's optional) ───
echo
echo "▸ CloudTrail (best-effort)"

cat > /tmp/cb-trail-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AWSCloudTrailAclCheck",
      "Effect": "Allow",
      "Principal": { "Service": "cloudtrail.amazonaws.com" },
      "Action": "s3:GetBucketAcl",
      "Resource": "arn:aws:s3:::${TRAIL_BUCKET}"
    },
    {
      "Sid": "AWSCloudTrailWrite",
      "Effect": "Allow",
      "Principal": { "Service": "cloudtrail.amazonaws.com" },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${TRAIL_BUCKET}/AWSLogs/${ACCOUNT}/*",
      "Condition": { "StringEquals": { "s3:x-amz-acl": "bucket-owner-full-control" } }
    }
  ]
}
EOF
aws s3api put-bucket-policy --bucket "$TRAIL_BUCKET" --policy file:///tmp/cb-trail-policy.json --region "$REGION" 2>/dev/null || true

if ! aws cloudtrail describe-trails --trail-name-list "${PREFIX}-trail" --region "$REGION" \
    --query 'trailList | length(@)' --output text 2>/dev/null | grep -q '^1$'; then
  aws cloudtrail create-trail --name "${PREFIX}-trail" --s3-bucket-name "$TRAIL_BUCKET" --region "$REGION" 2>/dev/null \
    && aws cloudtrail start-logging --name "${PREFIX}-trail" --region "$REGION" \
    && echo "  ✓ trail created" \
    || echo "  ⚠ skipped (insufficient permissions or already exists)"
else
  echo "  ✓ trail already exists"
fi

# ── Lambda log archiver ─────────────────────────────────
echo
echo "▸ Lambda log archiver"

LAMBDA_DIR="$(cd "$(dirname "$0")/../../lambda/log-archiver" && pwd)"

# Zip the function
cd "$LAMBDA_DIR"
zip -q -j /tmp/cb-lambda.zip handler.py

# Lambda IAM role
ROLE_NAME="${PREFIX}-lambda-role"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  cat > /tmp/cb-lambda-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document file:///tmp/cb-lambda-trust.json >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name LogArchiver \
    --policy-document "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Effect\": \"Allow\",
        \"Action\": [\"logs:DescribeLogGroups\", \"logs:DescribeLogStreams\",
                     \"logs:FilterLogEvents\", \"s3:PutObject\"],
        \"Resource\": \"*\"
      }]
    }"
  echo "  waiting 10 s for role to propagate..."
  sleep 10
fi
ROLE_ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE_NAME}"

FUNC="${PREFIX}-log-archiver"
if aws lambda get-function --function-name "$FUNC" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FUNC" \
    --zip-file fileb:///tmp/cb-lambda.zip --region "$REGION" >/dev/null
  echo "  ✓ Lambda code updated"
else
  aws lambda create-function --function-name "$FUNC" \
    --runtime python3.11 --handler handler.lambda_handler \
    --role "$ROLE_ARN" --zip-file fileb:///tmp/cb-lambda.zip \
    --timeout 60 --region "$REGION" \
    --environment "Variables={LOG_GROUP=${LOG_GROUP},BUCKET=${LOGS_BUCKET}}" >/dev/null
  echo "  ✓ Lambda created"
fi

# ── Write outputs for the deploy script ─────────────────
echo
cat > /tmp/cb-outputs.env <<EOF
export CB_ACCOUNT="$ACCOUNT"
export CB_REGION="$REGION"
export CB_SNS_TOPIC_ARN="$SNS_ARN"
export CB_MODELS_BUCKET="$MODELS_BUCKET"
export CB_LOGS_BUCKET="$LOGS_BUCKET"
export CB_DYNAMODB_USERS="${PREFIX}-users"
export CB_DYNAMODB_DECISIONS="${PREFIX}-decisions"
export CB_DYNAMODB_AUDIT="${PREFIX}-audit"
export CB_LAMBDA_FN="$FUNC"
EOF

echo "════════════════════════════════════════════════════════"
echo "✓ Supporting AWS resources created"
echo "  Saved env vars to /tmp/cb-outputs.env"
echo "════════════════════════════════════════════════════════"
