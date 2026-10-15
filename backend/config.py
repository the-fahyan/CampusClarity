"""Configuration loading for CampusMate AI.

Responsibility (DESIGN.md §1.2): environment loading (`.env` via pydantic-settings)
and fail-fast validation. Holds no business logic and no hardcoded secrets.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PLACEHOLDER_KEY = "your_key_here"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid (fails fast at startup)."""


class Settings(BaseSettings):
    """Environment-backed settings (DESIGN.md §6.2)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- LLM / Gemini ---
    GEMINI_API_KEY: str = ""
    GEMMA_MODEL_ID: str = "gemma-3-27b-it"
    GEMMA_FALLBACK_MODEL_ID: str = "gemma-3-12b-it"
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"

    # --- Retrieval / abstention gate ---
    BM25_MIN_SCORE: float = 10.5  # calibrated (Phase 6); see docs/DECISIONS.md
    BM25_TOP_K: int = 5

    # --- API limits ---
    RATE_LIMIT_PER_MINUTE: int = 60
    MAX_QUESTION_LENGTH: int = 500
    MIN_QUESTION_LENGTH: int = 3
    MAX_BODY_BYTES: int = 8 * 1024

    # --- Dev/QA ---
    MOCK_LLM: bool = False

    # --- Server ---
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # --- Paths (relative to project root) ---
    INDEX_DIR: str = "index"
    SOURCES_DIR: str = "data/sources"
    FRONTEND_DIR: str = "frontend"

    # --- App metadata ---
    APP_VERSION: str = "1.0.0"

    @field_validator("MOCK_LLM", mode="before")
    @classmethod
    def _coerce_mock_llm(cls, v: object) -> object:
        """Accept 'true'/'false'/'1'/'0'/'' from env files and shell."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on"}
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _validate_key(self) -> "Settings":
        """Fail fast when a live key is required but missing (FR-18)."""
        key = (self.GEMINI_API_KEY or "").strip()
        if not self.MOCK_LLM and (not key or key == PLACEHOLDER_KEY):
            raise ConfigError(
                "GEMINI_API_KEY is not set and MOCK_LLM is not enabled. "
                "Set GEMINI_API_KEY in .env, or set MOCK_LLM=true for keyless development."
            )
        return self

    @property
    def llm_mode(self) -> str:
        """`mock` or `live` — reported by /api/health (§5.5)."""
        return "mock" if self.MOCK_LLM else "live"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (import-time friendly, test-overridable)."""
    return Settings()  # type: ignore[call-arg]
