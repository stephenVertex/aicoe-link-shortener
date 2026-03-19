#!/usr/bin/env bash
# One-time infrastructure setup for als-mcp on ECS Fargate.
#
# This script documents how the AWS resources were originally created.
# It is IDEMPOTENT-ISH but primarily serves as a reference.
# The actual resources already exist — use deploy.sh for routine deployments.
#
# Requires: aws cli with profile 'cf2'
set -euo pipefail

PROFILE="cf2"
REGION="us-east-1"
ACCOUNT_ID="552960913849"

# ---------- ECR ----------
echo "==> Creating ECR repository..."
aws --profile "${PROFILE}" ecr create-repository \
  --repository-name als-mcp \
  --image-scanning-configuration scanOnPush=true \
  --region "${REGION}" 2>/dev/null || echo "    (already exists)"

# ---------- VPC ----------
echo "==> Creating VPC..."
VPC_ID=$(aws --profile "${PROFILE}" ec2 create-vpc \
  --cidr-block 10.99.0.0/16 \
  --query 'Vpc.VpcId' --output text \
  --region "${REGION}" 2>/dev/null || echo "vpc-0dbe71737db2aea3f")
aws --profile "${PROFILE}" ec2 create-tags \
  --resources "${VPC_ID}" \
  --tags Key=Name,Value=als-mcp-vpc Key=project,Value=als-mcp \
  --region "${REGION}" 2>/dev/null || true
echo "    VPC: ${VPC_ID}"

# Enable DNS support
aws --profile "${PROFILE}" ec2 modify-vpc-attribute \
  --vpc-id "${VPC_ID}" --enable-dns-support '{"Value":true}' \
  --region "${REGION}" 2>/dev/null || true
aws --profile "${PROFILE}" ec2 modify-vpc-attribute \
  --vpc-id "${VPC_ID}" --enable-dns-hostnames '{"Value":true}' \
  --region "${REGION}" 2>/dev/null || true

# ---------- Subnets ----------
echo "==> Creating subnets..."
SUBNET_A=$(aws --profile "${PROFILE}" ec2 create-subnet \
  --vpc-id "${VPC_ID}" --cidr-block 10.99.1.0/24 \
  --availability-zone us-east-1a \
  --query 'Subnet.SubnetId' --output text \
  --region "${REGION}" 2>/dev/null || echo "subnet-0623de716fffb9bbf")
SUBNET_B=$(aws --profile "${PROFILE}" ec2 create-subnet \
  --vpc-id "${VPC_ID}" --cidr-block 10.99.2.0/24 \
  --availability-zone us-east-1b \
  --query 'Subnet.SubnetId' --output text \
  --region "${REGION}" 2>/dev/null || echo "subnet-0bfacfb0550345d16")
echo "    Subnet A: ${SUBNET_A}"
echo "    Subnet B: ${SUBNET_B}"

# ---------- Internet Gateway ----------
echo "==> Creating Internet Gateway..."
IGW_ID=$(aws --profile "${PROFILE}" ec2 create-internet-gateway \
  --query 'InternetGateway.InternetGatewayId' --output text \
  --region "${REGION}" 2>/dev/null || echo "existing")
aws --profile "${PROFILE}" ec2 attach-internet-gateway \
  --internet-gateway-id "${IGW_ID}" --vpc-id "${VPC_ID}" \
  --region "${REGION}" 2>/dev/null || true

# Route table with default route to IGW
RT_ID=$(aws --profile "${PROFILE}" ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=${VPC_ID}" \
  --query 'RouteTables[0].RouteTableId' --output text \
  --region "${REGION}")
aws --profile "${PROFILE}" ec2 create-route \
  --route-table-id "${RT_ID}" --destination-cidr-block 0.0.0.0/0 \
  --gateway-id "${IGW_ID}" \
  --region "${REGION}" 2>/dev/null || true
aws --profile "${PROFILE}" ec2 associate-route-table \
  --route-table-id "${RT_ID}" --subnet-id "${SUBNET_A}" \
  --region "${REGION}" 2>/dev/null || true
aws --profile "${PROFILE}" ec2 associate-route-table \
  --route-table-id "${RT_ID}" --subnet-id "${SUBNET_B}" \
  --region "${REGION}" 2>/dev/null || true

# ---------- Security Groups ----------
echo "==> Creating security groups..."
ALB_SG=$(aws --profile "${PROFILE}" ec2 create-security-group \
  --group-name als-mcp-alb-sg \
  --description "ALB for als-mcp" \
  --vpc-id "${VPC_ID}" \
  --query 'GroupId' --output text \
  --region "${REGION}" 2>/dev/null || echo "sg-036e514ecd8964c11")
ECS_SG=$(aws --profile "${PROFILE}" ec2 create-security-group \
  --group-name als-mcp-ecs-sg \
  --description "ECS tasks for als-mcp" \
  --vpc-id "${VPC_ID}" \
  --query 'GroupId' --output text \
  --region "${REGION}" 2>/dev/null || echo "sg-02dc97762eb74e63f")

# ALB SG: allow HTTP from anywhere
aws --profile "${PROFILE}" ec2 authorize-security-group-ingress \
  --group-id "${ALB_SG}" --protocol tcp --port 80 --cidr 0.0.0.0/0 \
  --region "${REGION}" 2>/dev/null || true
# ECS SG: allow port 8000 from ALB SG only
aws --profile "${PROFILE}" ec2 authorize-security-group-ingress \
  --group-id "${ECS_SG}" --protocol tcp --port 8000 \
  --source-group "${ALB_SG}" \
  --region "${REGION}" 2>/dev/null || true

aws --profile "${PROFILE}" ec2 create-tags \
  --resources "${ALB_SG}" --tags Key=Name,Value=als-mcp-alb-sg Key=project,Value=als-mcp \
  --region "${REGION}" 2>/dev/null || true
aws --profile "${PROFILE}" ec2 create-tags \
  --resources "${ECS_SG}" --tags Key=Name,Value=als-mcp-ecs-sg Key=project,Value=als-mcp \
  --region "${REGION}" 2>/dev/null || true

# ---------- IAM Roles ----------
echo "==> Creating IAM roles..."

# Execution role (ECR pull + CloudWatch logs + SSM secrets)
aws --profile "${PROFILE}" iam create-role \
  --role-name als-mcp-exec-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' 2>/dev/null || true
aws --profile "${PROFILE}" iam attach-role-policy \
  --role-name als-mcp-exec-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy \
  2>/dev/null || true
aws --profile "${PROFILE}" iam put-role-policy \
  --role-name als-mcp-exec-role \
  --policy-name als-mcp-ssm-read \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["ssm:GetParameters"],
      "Resource": "arn:aws:ssm:*:*:parameter/als-mcp/*"
    }]
  }' 2>/dev/null || true

# Task role (minimal — no extra permissions needed)
aws --profile "${PROFILE}" iam create-role \
  --role-name als-mcp-task-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' 2>/dev/null || true

# ---------- CloudWatch Log Group ----------
echo "==> Creating CloudWatch log group..."
aws --profile "${PROFILE}" logs create-log-group \
  --log-group-name /ecs/als-mcp \
  --region "${REGION}" 2>/dev/null || true

# ---------- ALB + Target Group ----------
echo "==> Creating ALB..."
ALB_ARN=$(aws --profile "${PROFILE}" elbv2 create-load-balancer \
  --name als-mcp-alb \
  --subnets "${SUBNET_A}" "${SUBNET_B}" \
  --security-groups "${ALB_SG}" \
  --scheme internet-facing \
  --type application \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text \
  --region "${REGION}" 2>/dev/null || \
  aws --profile "${PROFILE}" elbv2 describe-load-balancers --names als-mcp-alb \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text --region "${REGION}")
echo "    ALB: ${ALB_ARN}"

echo "==> Creating target group..."
TG_ARN=$(aws --profile "${PROFILE}" elbv2 create-target-group \
  --name als-mcp-tg \
  --protocol HTTP --port 8000 \
  --vpc-id "${VPC_ID}" \
  --target-type ip \
  --health-check-path /health \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --query 'TargetGroups[0].TargetGroupArn' --output text \
  --region "${REGION}" 2>/dev/null || \
  aws --profile "${PROFILE}" elbv2 describe-target-groups --names als-mcp-tg \
    --query 'TargetGroups[0].TargetGroupArn' --output text --region "${REGION}")
echo "    Target group: ${TG_ARN}"

echo "==> Creating listener (HTTP:80 → target group)..."
aws --profile "${PROFILE}" elbv2 create-listener \
  --load-balancer-arn "${ALB_ARN}" \
  --protocol HTTP --port 80 \
  --default-actions "Type=forward,TargetGroupArn=${TG_ARN}" \
  --region "${REGION}" 2>/dev/null || true

# ---------- ECS Cluster + Service ----------
echo "==> Creating ECS cluster..."
aws --profile "${PROFILE}" ecs create-cluster \
  --cluster-name als-mcp-cluster \
  --region "${REGION}" 2>/dev/null || true

echo "==> Registering task definition..."
TASK_DEF_ARN=$(aws --profile "${PROFILE}" ecs register-task-definition \
  --cli-input-json "file://$(dirname "$0")/task-definition.json" \
  --region "${REGION}" \
  --query 'taskDefinition.taskDefinitionArn' --output text)
echo "    Task def: ${TASK_DEF_ARN}"

echo "==> Creating ECS service..."
aws --profile "${PROFILE}" ecs create-service \
  --cluster als-mcp-cluster \
  --service-name als-mcp-service \
  --task-definition "${TASK_DEF_ARN}" \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_A},${SUBNET_B}],securityGroups=[${ECS_SG}],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=${TG_ARN},containerName=als-mcp,containerPort=8000" \
  --region "${REGION}" 2>/dev/null || echo "    (service already exists)"

echo ""
echo "==> Infrastructure setup complete!"
echo "    ALB DNS: $(aws --profile "${PROFILE}" elbv2 describe-load-balancers \
  --names als-mcp-alb --query 'LoadBalancers[0].DNSName' --output text --region "${REGION}")"
echo "    MCP endpoint: http://<ALB_DNS>/sse"
