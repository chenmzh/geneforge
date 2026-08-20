"""Application settings — 12-factor style, all overridable by environment."""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app -------------------------------------------------------------- #
    app_name: str = "GeneForge"
    app_version: str = "0.1.0"
    environment: str = Field(default="development")
    debug: bool = True
    api_prefix: str = "/api/v1"
    root_path: str = ""

    # --- security --------------------------------------------------------- #
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    access_token_ttl_minutes: int = 60 * 12
    refresh_token_ttl_days: int = 14
    password_min_length: int = 8
    pbkdf2_iterations: int = 240_000
    allow_registration: bool = True
    first_superuser_email: str = "admin@geneforge.local"
    first_superuser_password: str = "ChangeMe123!"
    cors_origins: CsvList = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

    # --- database --------------------------------------------------------- #
    database_url: str = f"sqlite:///{BACKEND_DIR / 'geneforge.db'}"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- task queue ------------------------------------------------------- #
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    task_local_workers: int = 4
    task_max_runtime_seconds: int = 900

    # --- storage ---------------------------------------------------------- #
    storage_dir: Path = BACKEND_DIR / "storage"
    max_upload_bytes: int = 64 * 1024 * 1024
    max_sequence_length: int = 5_000_000
    # Snapshot a new version when only features change (annotation curation is
    # undoable). Each snapshot stores the full sequence text, so deployments that
    # hold genome-scale records may prefer to disable it.
    version_feature_edits: bool = True

    # --- limits / tools --------------------------------------------------- #
    align_max_cells_sync: int = 4_000_000
    async_job_length_threshold: int = 200_000
    default_enzyme_set: str = "common"

    # --- external resources ---------------------------------------------- #
    external_proxy_enabled: bool = True
    external_proxy_allowlist: CsvList = Field(
        default_factory=lambda: [
            "eutils.ncbi.nlm.nih.gov",
            "rest.ensembl.org",
            "www.ebi.ac.uk",
            "rest.uniprot.org",
            "api.addgene.org",
        ]
    )
    external_proxy_timeout_seconds: int = 20

    # --- frontend --------------------------------------------------------- #
    serve_frontend: bool = True
    frontend_dist: Path = BACKEND_DIR / "app" / "static"

    @field_validator("cors_origins", "external_proxy_allowlist", mode="before")
    @classmethod
    def _split_csv(cls, value):
        if isinstance(value, str):
            if value.strip().startswith("["):
                return value
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def queue_enabled(self) -> bool:
        return bool(self.celery_broker_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
