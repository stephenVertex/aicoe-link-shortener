# als-mcp Infrastructure Reference

Live AWS resources for the MCP server deployment (profile: `cf2`, region: `us-east-1`).

## Endpoint

**MCP SSE**: `http://als-mcp-alb-1979469047.us-east-1.elb.amazonaws.com/sse`
**Health**: `http://als-mcp-alb-1979469047.us-east-1.elb.amazonaws.com/health`

## ECR

- Repository: `552960913849.dkr.ecr.us-east-1.amazonaws.com/als-mcp`
- Image tag: `latest`
- Scan on push: enabled

## ECS

- Cluster: `als-mcp-cluster`
- Service: `als-mcp-service` (1 desired, Fargate, ROLLING deployment)
- Task definition: `als-mcp-task` (256 CPU / 512 MB)
- Container port: 8000

## Networking

- VPC: `vpc-0dbe71737db2aea3f` (10.99.0.0/16, tagged `als-mcp-vpc`)
- Subnets:
  - `subnet-0623de716fffb9bbf` (us-east-1a, 10.99.1.0/24)
  - `subnet-0bfacfb0550345d16` (us-east-1b, 10.99.2.0/24)
- ALB: `als-mcp-alb` (internet-facing, HTTP:80 → target group)
- ALB SG: `sg-036e514ecd8964c11` (inbound TCP 80 from 0.0.0.0/0)
- ECS SG: `sg-02dc97762eb74e63f` (inbound TCP 8000 from ALB SG only)
- Target group: `als-mcp-tg` (HTTP:8000, IP target type, health check on `/health`)

## IAM

- Execution role: `als-mcp-exec-role`
  - Attached: `AmazonECSTaskExecutionRolePolicy`
  - Inline: `als-mcp-ssm-read` (ssm:GetParameters on `arn:aws:ssm:*:*:parameter/als-mcp/*`)
- Task role: `als-mcp-task-role`

## Secrets

- API key: SSM Parameter Store at `/als-mcp/api-key` → injected as `ALS_API_KEY` env var

## CloudWatch

- Log group: `/ecs/als-mcp` (stream prefix: `ecs`)

## Redeployment

```bash
./mcp-server/deploy.sh           # Full deploy (build + push + ECS update)
./mcp-server/deploy.sh --build-only  # Just build and push image
```
