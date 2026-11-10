# Deploy backend to AWS (Lambda + API Gateway)

Stack lives in `infra/sam/template.yaml`. It wires an existing VPC, RDS PostgreSQL, and S3 bucket to a container-based Lambda function.

## Prerequisites

- AWS CLI and [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Docker (for `sam build` image builds)
- RDS reachable from Lambda subnets (security group + RDS SG allows 5432 from Lambda SG)
- Lambda subnets with egress (NAT gateway or VPC endpoints for S3 and Secrets Manager)
- S3 bucket for uploads (production requires `S3_BUCKET_NAME`; local disk is not used on Lambda)
- Secrets Manager secrets:
  - **Database password** — plain string secret
  - **JWT secret** — plain string, at least 32 characters (`uv run generate-jwt-secret`)

## One-time database setup

From a host that can reach RDS (bastion, VPN, or CI with network access):

```bash
export ENV=production
# Set DATABASE_* to RDS values (or use a production .env)
uv run alembic upgrade head
uv run bootstrap
uv run seed-permissions
```

Schema migrations are **not** run on merge to `master`; repeat `alembic upgrade head` when migrations ship.

## First deploy (manual)

```bash
cp infra/sam/samconfig.toml.example samconfig.toml
# Edit samconfig.toml — prod.parameter_overrides with your ARNs and IDs

sam build -t infra/sam/template.yaml
sam deploy --config-env prod
```

Note the **HttpApiUrl** output. Set the frontend `API_URL` to that value (no trailing slash).

Smoke checks:

```bash
curl -sS "$HTTP_API_URL/health"
curl -sS "$HTTP_API_URL/health/ready"
```

## Continuous deployment

Merges to **`master`** run `.github/workflows/deploy-aws.yml` after CI passes, using GitHub OIDC (no long-lived AWS keys).

### AWS Amplify (frontend)

The frontend repo deploys on push to **`master`** when Amplify Hosting is connected to Git. See `aagman-erp-fe/docs/deploy-amplify.md`. No ECR or OIDC is required for Amplify builds.

### GitHub OIDC (one-time)

1. IAM identity provider: `token.actions.githubusercontent.com`
2. IAM role trusted by your repo, branch `master`, e.g. `repo:ORG/aagman-erp-be:ref:refs/heads/master`
3. Attach policies for CloudFormation, Lambda, API Gateway, ECR, IAM pass-role, and S3 used by SAM deploy
4. GitHub repo → Settings → Environments → **production**:
   - Variable `AWS_ROLE_ARN` — deploy role ARN
   - Variable `AWS_REGION` — e.g. `ap-south-1`
   - Secret `SAM_PARAMETER_OVERRIDES` — same string as `parameter_overrides` in `samconfig.toml.example` (no newlines)

### ECR

`sam deploy` with `resolve_image_repos = true` creates or reuses an ECR repository for the function image.

## Configuration reference

| Variable (Lambda) | Source |
|-------------------|--------|
| `CORS_ORIGINS` | SAM parameter — Amplify app URL |
| `TRUSTED_PROXY_COUNT` | `1` (API Gateway) |
| `DATABASE_*` | SAM parameters + password secret |
| `JWT_SECRET` | Secrets Manager |
| `S3_BUCKET_NAME` | SAM parameter; IAM role for S3 (no access keys) |

## Local image smoke test

```bash
docker build -f Dockerfile.lambda -t aagman-erp-api:local .
# Requires env at runtime — prefer sam local or deployed stack for integration tests
```

## Auth rate limiting

In-memory limits in `app/core/rate_limit.py` apply per Lambda instance, not globally across concurrent executions.
