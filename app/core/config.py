"""Environment-backed application configuration."""

import os
from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _settings_env_file() -> str:
    if os.environ.get("ENV", "").strip().lower() == "testing":
        return ".env.test"
    return ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_settings_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["development", "testing", "staging", "production"] = "development"
    app_name: str = "Aagman ERP API"
    app_version: str = "0.1.0"
    debug: bool = False
    auto_sync_permissions: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_v1_prefix: str = "/api/v1"

    database_host: str = "127.0.0.1"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "aagman_erp"
    database_user: str = "postgres"
    database_password: SecretStr = SecretStr("postgres")
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout_seconds: int = Field(default=30, ge=1)
    database_pool_recycle_seconds: int = Field(default=1800, ge=0)

    rate_limit_window_seconds: int = Field(default=60, ge=1)

    jwt_secret: SecretStr = Field(
        default=SecretStr("dev-only-change-me-use-32-chars-min!!"),
        min_length=32,
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_token_ttl_minutes: int = Field(default=30, ge=1)
    jwt_refresh_token_ttl_minutes: int = Field(default=10_080, ge=1)
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    password_reset_ttl_minutes: int = Field(default=60, ge=5, le=1_440)

    cors_origins: Annotated[list[AnyHttpUrl], NoDecode] = Field(default_factory=list)
    auth_rate_limit_requests: int = Field(default=20, ge=1)
    trusted_proxy_count: int = Field(default=0, ge=0)

    upload_dir: str = "uploads"
    max_upload_size_mb: int = Field(default=10, ge=1)
    public_app_url: AnyHttpUrl | None = None

    aws_region: str | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    s3_bucket_name: str | None = None
    s3_endpoint_url: AnyHttpUrl | None = None
    s3_presign_ttl_seconds: int = Field(default=300, ge=1, le=86_400)

    @property
    def database_url(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=quote(self.database_user, safe=""),
            password=quote(self.database_password.get_secret_value(), safe=""),
            host=self.database_host,
            port=self.database_port,
            path=self.database_name,
        )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
