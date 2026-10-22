"""Application settings, read exclusively from environment variables / backend .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Data
    data_dir: Path = BACKEND_DIR / "data"
    duckdb_filename: str = "retail.duckdb"
    app_db_filename: str = "app_state.sqlite3"
    source_excel_path: Path = PROJECT_DIR / "online+retail+ii" / "online_retail_II.xlsx"

    # LLM: "auto" (DeepSeek if DEEPSEEK_API_KEY is set, else Anthropic if ANTHROPIC_API_KEY is set,
    # else offline), "deepseek", "anthropic", or "offline" (deterministic rule-based, no LLM)
    llm_provider: str = "auto"
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "low"
    llm_timeout_seconds: float = 60.0

    # Retrieval of verified examples for the LLM prompt: "bge-faiss", "keyword" or "none"
    retrieval_backend: str = "bge-faiss"
    embedding_model: str = "BAAI/bge-large-en-v1.5"

    # Query safety
    query_timeout_seconds: float = 10.0
    max_result_rows: int = 1000
    max_question_length: int = 500

    # Dataset imports
    max_upload_mb: int = 50
    max_import_columns: int = 200

    # Query-result cache (in-process, bounded)
    cache_ttl_seconds: int = 600
    cache_max_entries: int = 256

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def duckdb_path(self) -> Path:
        return self.data_dir / self.duckdb_filename

    @property
    def datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / self.app_db_filename


@lru_cache
def get_settings() -> Settings:
    return Settings()
