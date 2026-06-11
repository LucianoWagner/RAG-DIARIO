"""
Centralized configuration for the Hemeroteca RAG backend.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "llama3.1:8b"
    embedding_provider: str = "local"  # "local" or "gemini"
    embedding_model: str = "intfloat/multilingual-e5-large"
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    scope_embedding_threshold: float = 0.15
    scope_llm_model: str = "qwen2.5:3b-instruct"
    scope_llm_enabled: bool = True

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "hemeroteca_la_plata"
    qdrant_api_key: str | None = None
    qdrant_prefer_grpc: bool = False

    chunk_size: int = 900
    chunk_overlap: int = 120

    top_k: int = 20
    rerank_top_n: int = 8
    semantic_weight: float = 0.5
    bm25_weight: float = 0.5

    min_top_score: float = 0.3
    min_relevant_chunks: int = 2
    relevance_threshold: float = 0.25

    scraper_user_agent: str = "HemerotecaLaPlataAcademic/1.0"
    scraper_rate_limit_seconds: float = 2.0
    scraper_target_year: int = 2005
    scraper_target_date: str = "17-03-2005"
    scraper_max_days: int | None = 7
    scraper_discovery_mode: str = "auto"
    scraper_search_terms: str = "La Plata"
    scraper_max_search_pages: int = 3

    data_dir: str = "backend/data"
    raw_data_dir: str = "backend/data/raw"
    parsed_data_dir: str = "backend/data/parsed"
    enriched_data_dir: str = "backend/data/enriched"
    gazetteer_path: str = "backend/data/gazetteer/argentina.json"

    request_timeout_seconds: float = 20.0

    reranker_model_name: str = "ms-marco-MultiBERT-L-12"
    reranker_type: str = "flashrank"  # "flashrank" or "cross-encoder"
    log_level: str = "INFO"

    model_cache_dir: str | None = Field(default=None)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
