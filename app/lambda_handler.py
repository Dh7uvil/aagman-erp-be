"""AWS Lambda entry point (API Gateway HTTP API via Mangum)."""

from __future__ import annotations

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="auto")
