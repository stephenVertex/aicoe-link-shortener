#!/usr/bin/env bash
# Deploy the als-mcp FastMCP server to ECS Fargate.
#
# Usage:
#   ./mcp-server/deploy.sh              # build, push, and deploy
#   ./mcp-server/deploy.sh --build-only # build and push image only
#
# Requires: aws cli with profile 'cf2', docker
set -euo pipefail

PROFILE="cf2"
REGION="us-east-1"
ACCOUNT_ID="552960913849"
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/als-mcp"
ECS_CLUSTER="als-mcp-cluster"
ECS_SERVICE="als-mcp-service"
TASK_FAMILY="als-mcp-task"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BUILD_ONLY=false
if [[ "${1:-}" == "--build-only" ]]; then
  BUILD_ONLY=true
fi

echo "==> Authenticating with ECR..."
aws --profile "${PROFILE}" ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "==> Building Docker image..."
docker build -t als-mcp:latest -f "${SCRIPT_DIR}/Dockerfile" "${REPO_ROOT}"

echo "==> Tagging and pushing to ECR..."
docker tag als-mcp:latest "${ECR_REPO}:latest"
docker push "${ECR_REPO}:latest"

if $BUILD_ONLY; then
  echo "==> Build-only mode — skipping ECS deployment."
  exit 0
fi

echo "==> Registering new task definition..."
TASK_DEF_ARN=$(aws --profile "${PROFILE}" ecs register-task-definition \
  --cli-input-json "file://${SCRIPT_DIR}/task-definition.json" \
  --region "${REGION}" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)
echo "    Task definition: ${TASK_DEF_ARN}"

echo "==> Updating ECS service to use new task definition..."
aws --profile "${PROFILE}" ecs update-service \
  --cluster "${ECS_CLUSTER}" \
  --service "${ECS_SERVICE}" \
  --task-definition "${TASK_DEF_ARN}" \
  --force-new-deployment \
  --region "${REGION}" \
  --query 'service.serviceName' \
  --output text

echo "==> Waiting for service to stabilize..."
aws --profile "${PROFILE}" ecs wait services-stable \
  --cluster "${ECS_CLUSTER}" \
  --services "${ECS_SERVICE}" \
  --region "${REGION}"

echo "==> Deployment complete!"
echo "    Endpoint: http://als-mcp-alb-1979469047.us-east-1.elb.amazonaws.com/sse"
