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
    # When set, the test suite uses this URL instead of `database_url` so the
    # autouse TRUNCATE fixture never touches the dev/prod database. Conftest
    # falls back to deriving `<database_url>_test` if this is left empty.
    test_database_url: str = Field(default="", alias="TEST_DATABASE_URL")

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

    # Auth (Phase 1)
    allow_public_registration: bool = Field(default=True, alias="ALLOW_PUBLIC_REGISTRATION")
    password_min_length: int = Field(default=12, alias="PASSWORD_MIN_LENGTH")
    hibp_user_agent: str = Field(default="secure-docstore-dev", alias="HIBP_USER_AGENT")
    hibp_timeout_seconds: float = Field(default=5.0, alias="HIBP_TIMEOUT_SECONDS")
    hibp_enabled: bool = Field(default=True, alias="HIBP_ENABLED")
    session_lifetime_hours: int = Field(default=12, alias="SESSION_LIFETIME_HOURS")

    # Files (Phase 2)
    max_upload_size_mb: int = Field(default=50, alias="MAX_UPLOAD_SIZE_MB")

    # Envelope encryption (Phase 3)
    # 32 random bytes, base64-encoded. In dev we fall back to a derivation
    # from SECRET_KEY (deterministic, with a loud warning).
    kek_base64: str = Field(default="", alias="KEK")
    kek_version: int = Field(default=1, alias="KEK_VERSION")

    # Classifier (Phase 4)
    # Default is the v6 English DeBERTa-v3 base. Set CLASSIFIER_MULTILINGUAL=true
    # to switch to bge-m3 (XLM-RoBERTa) for Cyrillic / CJK / non-English content.
    classifier_multilingual: bool = Field(default=False, alias="CLASSIFIER_MULTILINGUAL")
    classifier_disable_presidio: bool = Field(default=False, alias="CLASSIFIER_DISABLE_PRESIDIO")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_development(self) -> bool:
        return self.flask_env.lower() in {"development", "dev"}

    @property
    def effective_test_database_url(self) -> str:
        """The URL pytest connects to. Either the explicit `TEST_DATABASE_URL`
        env var, or `<database_url>_test` (swap the trailing db name).
        Tests must NEVER share a database with the dev/prod app.
        """
        if self.test_database_url:
            return self.test_database_url
        # Replace just the final path segment (the db name).
        scheme, _, rest = self.database_url.partition("://")
        userhost, _, dbname = rest.rpartition("/")
        return f"{scheme}://{userhost}/{dbname}_test"

    @property
    def registration_open_to_public(self) -> bool:
        """Public registration only in dev AND only when explicitly enabled."""
        return self.is_development and self.allow_public_registration


settings = Settings()
