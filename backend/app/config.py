"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field, model_validator
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
    database_url: str = Field(default="", alias="DATABASE_URL")
    # When set, the test suite uses this URL instead of `database_url` so the
    # autouse TRUNCATE fixture never touches the dev/prod database. Conftest
    # falls back to deriving `<database_url>_test` if this is left empty.
    test_database_url: str = Field(default="", alias="TEST_DATABASE_URL")

    # Redis / Celery
    redis_url: str = Field(default="", alias="REDIS_URL")

    # MinIO
    minio_endpoint: str = Field(default="minio:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="documents", alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")

    @model_validator(mode="after")
    def _build_urls_from_components(self) -> Settings:
        """Construct DATABASE_URL, REDIS_URL, and MinIO creds from individual
        env vars when the composite URL is not provided directly.  This lets
        docker-compose keep passwords out of interpolated strings — sensitive
        values arrive via env_file (.env.init) as separate vars."""
        if not self.database_url:
            user = os.environ.get("POSTGRES_USER", "docstore")
            pwd = os.environ.get("POSTGRES_PASSWORD", "docstore")
            host = os.environ.get("POSTGRES_HOST", "db")
            db = os.environ.get("POSTGRES_DB", "docstore")
            self.database_url = (
                f"postgresql+psycopg://{user}:{pwd}@{host}:5432/{db}"
            )
        if not self.redis_url:
            pwd = os.environ.get("REDIS_PASSWORD", "")
            host = os.environ.get("REDIS_HOST", "redis")
            self.redis_url = f"redis://:{pwd}@{host}:6379/0"
        if not os.environ.get("MINIO_SECRET_KEY"):
            self.minio_secret_key = os.environ.get(
                "MINIO_ROOT_PASSWORD", "minioadmin"
            )
        if not os.environ.get("MINIO_ACCESS_KEY"):
            self.minio_access_key = os.environ.get(
                "MINIO_ROOT_USER", "minioadmin"
            )
        return self
    # Like TEST_DATABASE_URL, but for the object store. Tests wipe their bucket
    # every run; sharing it with dev would clobber uploaded files.
    test_minio_bucket: str = Field(default="", alias="TEST_MINIO_BUCKET")

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
    # Default is English DeBERTa-v3 large (the model the experiments measured). Set
    # CLASSIFIER_MULTILINGUAL=true to switch to bge-m3 for Cyrillic / CJK / non-English content.
    # CLASSIFIER_MODEL=base picks the smaller DeBERTa; any other value is a Hugging Face checkpoint.
    classifier_multilingual: bool = Field(default=False, alias="CLASSIFIER_MULTILINGUAL")
    classifier_model: str = Field(default="large", alias="CLASSIFIER_MODEL")
    classifier_disable_presidio: bool = Field(default=False, alias="CLASSIFIER_DISABLE_PRESIDIO")
    # Semantic layer: "nli" (zero-shot model above) or "llm" (llama-server at LLM_BASE_URL).
    classifier_engine: Literal["nli", "llm"] = Field(default="nli", alias="CLASSIFIER_ENGINE")
    # Prompt-injection defenses, comma-separated: D1 hardened LLM prompt, D2 classify the
    # visible text too and keep the higher tier, D4 injection detector (flag -> RESTRICTED),
    # D6 Presidio also scans a copy with look-alike characters / separators folded back.
    classifier_defenses: str = Field(default="", alias="CLASSIFIER_DEFENSES")
    classifier_detector: Literal["pg2", "protectai"] = Field(
        default="pg2", alias="CLASSIFIER_DETECTOR"
    )
    llm_base_url: str = Field(default="http://host.docker.internal:18080", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gemma4-12b", alias="LLM_MODEL")
    llm_prompt: str = Field(default="classify_v1", alias="LLM_PROMPT")
    llm_timeout: int = Field(default=120, alias="LLM_TIMEOUT")
    # Admin playground (compare classifier setups on one document). Off unless PLAYGROUND=1;
    # its NLI forward pass runs on the host NLI server (research/nli_server.py, GPU).
    playground: bool = Field(default=False, alias="PLAYGROUND")
    playground_nli_url: str = Field(
        default="http://host.docker.internal:18081", alias="PLAYGROUND_NLI_URL"
    )

    @property
    def defenses(self) -> frozenset[str]:
        return frozenset(d.strip().upper() for d in self.classifier_defenses.split(",") if d.strip())

    @model_validator(mode="after")
    def _check_defenses(self) -> Settings:
        if unknown := self.defenses - {"D1", "D2", "D4", "D6"}:
            raise ValueError(f"CLASSIFIER_DEFENSES: unknown {sorted(unknown)}; known: D1, D2, D4, D6")
        return self

    # Vault (optional — infrastructure hardening)
    vault_addr: str = Field(default="", alias="VAULT_ADDR")
    vault_token: str = Field(default="", alias="VAULT_TOKEN")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Phase 11: SIEM-friendly event stream ---
    # Where the ECS-shaped NDJSON event log lives. Filebeat / Wazuh agent
    # tails this file; one event per line. Empty string disables file output
    # (events still go to the DB + stdout).
    event_log_path: str = Field(
        default="/var/log/docstore/events.jsonl", alias="EVENT_LOG_PATH"
    )
    event_log_max_bytes: int = Field(
        default=50 * 1024 * 1024, alias="EVENT_LOG_MAX_BYTES"  # 50 MB
    )
    event_log_backup_count: int = Field(
        default=5, alias="EVENT_LOG_BACKUP_COUNT"
    )
    # Whether to send emails for critical-severity events (uses MAIL_SERVER).
    notifications_email_enabled: bool = Field(
        default=True, alias="NOTIFICATIONS_EMAIL_ENABLED"
    )

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
    def effective_test_minio_bucket(self) -> str:
        """The MinIO bucket pytest writes to. Either explicit `TEST_MINIO_BUCKET`
        or `<minio_bucket>-test`. Tests TRUNCATE this bucket every run, so it
        must NEVER equal the dev bucket.
        """
        if self.test_minio_bucket:
            return self.test_minio_bucket
        return f"{self.minio_bucket}-test"

    @property
    def registration_open_to_public(self) -> bool:
        """Public registration only in dev AND only when explicitly enabled."""
        return self.is_development and self.allow_public_registration


settings = Settings()
