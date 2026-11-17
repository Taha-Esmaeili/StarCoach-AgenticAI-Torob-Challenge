"""Centralized .env configuration for all API keys, DB/Redis parameters, RecSys weights, and geo bounds.

Zero important entity variables or thresholds are hardcoded in application logic;
all values can be overridden via environment variables or `.env`.
"""

import json
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime settings and hyperparameters loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Three Distinct Models: Decision Model (gemini-decision-1), LLM, and Embedding
    typesafe_api_key: str = ""
    typesafe_base_url: str = "https://generativelanguage.googleapis.com/v1beta/decisions"
    typesafe_model: str = "gemini-decision-1"
    typesafe_timeout_seconds: float = 10.0

    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    llm_api_key: str = ""
    llm_model: str = "gemini-flash-lite-latest"
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 20.0

    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 1536
    embedding_batch_size: int = 128

    # 2. PostgreSQL + pgvector & Redis Connections, Pools & Cache TTLs
    postgres_user: str = "torob"
    postgres_password: str = "torob_secret"
    postgres_db: str = "torob_db"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url: str = "postgresql://torob:torob_secret@localhost:5432/torob_db"
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 10
    postgres_command_timeout_seconds: float = 15.0

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_url: str = "redis://localhost:6379/0"
    redis_socket_timeout_seconds: float = 2.0
    redis_key_prefix: str = "torob"
    redis_session_ttl_seconds: int = 21600
    redis_profile_ttl_seconds: int = 86400
    redis_qcache_ttl_seconds: int = 300

    # 3. Clean Two-Layer Adaptive RecSys (5+1 Store Layer + Category-Agnostic Trait Memory)
    recsys_total_slots: int = 6
    recsys_default_store_weights_json: str = (
        '{"w_price":0.30,"w_distance":0.30,"w_open_now":0.30,"w_trust_freshness":0.30,"w_installment":0.30}'
    )

    recsys_price_decay_ratio: float = 0.15
    recsys_distance_decay_km: float = 8.0
    recsys_mention_score_threshold: float = 0.35
    recsys_unmentioned_tiebreaker_factor: float = 0.10
    recsys_custom_offer_top_k: int = 15
    recsys_price_prior_boost_weight: float = 0.12

    recsys_trait_cosine_candidate_threshold: float = 0.60
    recsys_trait_jev_same_aspect_noul: float = 0.70
    recsys_trait_transfer_noul_threshold: float = 0.72
    recsys_ephemeral_gift_noul_threshold: float = 0.60
    recsys_max_traits_per_query: int = 5
    recsys_max_stored_traits_per_user: int = 15
    recsys_max_preferences_per_aspect: int = 2
    recsys_trait_soft_step: float = 0.15
    recsys_trait_confirmed_step: float = 0.35
    recsys_trait_rival_decay: float = 0.92
    recsys_contrastive_feedback_lr: float = 0.15

    recsys_clarify_confidence_threshold: float = 0.45
    recsys_dissatisfied_noul_threshold: float = 0.70
    recsys_max_clarification_rounds: int = 2

    recsys_dealbreaker_noul_threshold: float = 0.70
    recsys_hurdle_penalty_multiplier: float = 0.15
    recsys_freshness_half_life_days: float = 14.0

    # 4. Geolocation, Tehran Bounding Box, Retrieval Limits & Server Settings
    default_user_id: str = "usr_tehran_default"
    default_user_lat: float = 35.7219
    default_user_lng: float = 51.3347
    tehran_lat_min: float = 35.40
    tehran_lat_max: float = 35.95
    tehran_lng_min: float = 51.00
    tehran_lng_max: float = 51.75
    default_search_radius_km: float = 15.0
    max_candidate_offers: int = 50
    top_ranked_stores_limit: int = 10

    torob_dataset_dir: Path = Path("./dataset")
    api_v1_prefix: str = "/api/v1"
    cors_allow_origins: str = "*"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def asyncpg_dsn(self) -> str:
        """Normalize SQLAlchemy-style DSN (`postgresql+asyncpg://`) to standard `postgresql://` for asyncpg."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def effective_embedding_base_url(self) -> str:
        """Return EMBEDDING_BASE_URL if set, else fall back to LLM_BASE_URL."""
        return self.embedding_base_url.strip() or self.llm_base_url

    @property
    def effective_embedding_api_key(self) -> str:
        """Return EMBEDDING_API_KEY if set, else fall back to LLM_API_KEY."""
        return self.embedding_api_key.strip() or self.llm_api_key

    @property
    def default_store_weights(self) -> dict[str, float]:
        """Parse RECSYS_DEFAULT_STORE_WEIGHTS_JSON into a 5-criteria float dict."""
        return {k: float(v) for k, v in json.loads(self.recsys_default_store_weights_json).items()}

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS_ALLOW_ORIGINS."""
        raw = self.cors_allow_origins.strip()
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def jev_engine_mode(self) -> str:
        """Report active System One engine mode."""
        return "typesafe_sdk" if bool(self.typesafe_api_key.strip()) else "openai_compatible_system_one"


settings = Settings()
