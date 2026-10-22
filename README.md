# Aagman ERP Backend

Single-tenant FastAPI backend for identity, organization settings, and shared preferences.

## Requirements

- Python 3.13
- PostgreSQL
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
cp .env.example .env
# Edit .env (database credentials and JWT_SECRET)
```

Apply migrations and bootstrap the singleton organization:

```bash
uv run alembic upgrade head
uv run bootstrap
uv run seed-permissions
```

`seed-permissions` inserts any missing catalog permissions and grants them to the Superadmin role. Run it again after the catalog changes. Bootstrap must already have created that role.

Generate a production JWT secret:

```bash
uv run generate-jwt-secret
```

## Object storage (MinIO, local)

Organization logos are stored in S3-compatible object storage. For local development:

```bash
docker compose up -d
```

Copy the `S3_*` and `AWS_*` values from `.env.example` into `.env`. The MinIO console is at http://127.0.0.1:9001 (`minioadmin` / `minioadmin`). Without `S3_BUCKET_NAME`, logos fall back to the `UPLOAD_DIR` on disk.

## Run API

```bash
uv run uvicorn app.main:app --reload
```

Health: `GET /health`  
API base: `/api/v1` (auth, users, roles, organization, branches, departments, warehouses, audit logs)

## Tests

Copy `.env.test.example` to `.env.test` if provided, or create `.env.test` with `ENV=testing` and `DATABASE_NAME=aagman_erp_test`.

```bash
uv run pytest
```
