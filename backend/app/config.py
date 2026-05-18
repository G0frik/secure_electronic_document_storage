"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config. Sourced from env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Flask
    secret_key: str = Field(default="dev-secret-change-me", alias="SECRET_KEY")
    flask_env: str = Field(default="production", alias="FLASK_ENV")

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://docstore:docstore@db:5432/docstore",
        alias="DATABASE_URL",
    )

    # Redis / Celery
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # MinIO
    minio_endpoint: str = Field(default="minio:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="documents", alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")

    # Mail
    mail_server: str = Field(default="mailhog", alias="MAIL_SERVER")
    mail_port: int = Field(default=1025, alias="MAIL_PORT")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_development(self) -> bool:
        return self.flask_env.lower() in {"development", "dev"}


settings = Settings()
