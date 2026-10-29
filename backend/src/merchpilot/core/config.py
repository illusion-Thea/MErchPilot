"""文件职责：集中读取和校验环境变量，为各基础设施组件提供类型化配置。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """集中声明环境变量及默认值，向全系统提供类型化运行配置。"""
    model_config = SettingsConfigDict(
        # 支持从仓库根目录、backend 目录或容器工作目录启动，避免本地质量门禁读不到根目录配置。
        env_file=(
            ".env",
            Path(__file__).resolve().parents[4] / ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "MerchPilot API"
    app_env: str = "development"
    app_debug: bool = False
    api_prefix: str = "/api/v1"
    mcp_internal_base_url: str = "http://mcp:8001"
    mcp_api_base_url: str = "http://api:8000/api/v1"
    mcp_public_base_url: str = "http://localhost:8001"
    mcp_path: str = "/mcp"
    mcp_request_timeout_seconds: float = Field(default=30, ge=1, le=300)
    cors_origins: str = (
        "http://localhost:3000,http://localhost:3001,"
        "http://127.0.0.1:3000,http://127.0.0.1:3001"
    )

    database_url: str = "postgresql+asyncpg://merchpilot:merchpilot@postgres:5432/merchpilot"
    database_pool_size: int = Field(default=20, ge=1, le=200)
    database_max_overflow: int = Field(default=30, ge=0, le=500)
    database_pool_timeout_seconds: float = Field(default=30, ge=1, le=300)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86_400)
    database_slow_query_threshold_ms: float = Field(default=500, ge=0, le=60_000)
    redis_url: str = "redis://redis:6379/0"
    redis_key_prefix: str = "mp"
    redis_lock_timeout_seconds: int = Field(default=900, ge=10, le=86_400)
    checkpoint_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=300, le=90 * 24 * 3600)
    checkpoint_history_limit: int = Field(default=20, ge=1, le=500)
    run_event_stream_maxlen: int = Field(default=2_000, ge=100, le=100_000)
    rate_limit_enabled: bool = True
    rate_limit_requests: int = Field(default=600, ge=1, le=100_000)
    rate_limit_tenant_requests: int = Field(default=5_000, ge=1, le=1_000_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    rate_limit_fail_open: bool = True
    distributed_lock_fail_open: bool = True
    project_distributed_lock_enabled: bool = False
    run_distributed_lock_enabled: bool = False
    agent_distributed_lock_enabled: bool = False
    milvus_uri: str = "http://milvus:19530"
    milvus_token: str = ""
    milvus_collection_name: str = "merchpilot_evidence_hybrid_v2"
    milvus_hybrid_search_enabled: bool = True
    milvus_dense_weight: float = Field(default=0.65, ge=0, le=1)
    milvus_sparse_weight: float = Field(default=0.35, ge=0, le=1)
    embedding_service_url: str = "http://embedding-service:8100"
    reranker_service_url: str = "http://reranker-service:8100"
    retrieval_timeout_seconds: float = 3.0
    model_service_timeout_seconds: float = 120.0
    embedding_dimension: int = 1024
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    max_import_file_bytes: int = 52_428_800
    multimodal_max_pages: int = Field(default=50, ge=1, le=500)
    multimodal_max_image_bytes: int = Field(default=8_388_608, ge=1_048_576, le=20_971_520)

    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    agent_node_max_attempts: int = Field(default=3, ge=1, le=10)
    agent_node_retry_base_seconds: float = Field(default=1.0, ge=0, le=60)
    approval_sla_hours: int = Field(default=24, ge=1, le=720)

    llm_model: str = "qwen-plus"
    llm_multimodal_model: str = "qwen-vl-max"
    llm_api_key: str = Field(default="", validation_alias="DASHSCOPE_API_KEY")
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 90.0

    model_service_role: str = "all"
    embedding_model_path: Path = Path("/models/bge-m3")
    embedding_model_version: str = "bge-m3-local-v1"
    embedding_inference_batch_size: int = Field(default=4, ge=1, le=64)
    embedding_max_length: int = Field(default=512, ge=64, le=8192)
    reranker_model_path: Path = Path("/models/bge-reranker-large")
    reranker_model_version: str = "bge-reranker-large-local-v1"
    reranker_batch_size: int = 8
    reranker_max_length: int = 512
    model_device: str = "auto"
    model_dtype: str = "auto"
    model_cpu_threads: int = Field(default=2, ge=1, le=32)

    local_storage_path: Path = Path("/data/files")
    object_storage_provider: str = "local"
    auth_mode: str = "local"
    allow_insecure_local_auth: bool = False
    local_auth_user_id: str = "local-user"
    local_auth_tenant_id: str = "default"
    local_auth_roles: str = "admin"
    local_auth_profiles: str = "admin,planner,approver,viewer"
    demo_workspace_enabled: bool = True
    external_approval_provider: str = "internal"
    telemetry_provider: str = "console"

    websocket_heartbeat_seconds: int = 15
    websocket_stream_block_ms: int = 10_000
    api_workers: int = Field(default=2, ge=1, le=32)
    api_keepalive_seconds: int = Field(default=5, ge=1, le=300)
    model_service_max_concurrency: int = Field(default=2, ge=1, le=128)
    model_service_queue_timeout_seconds: float = Field(default=2, ge=0.1, le=60)
    model_service_failure_threshold: int = Field(default=5, ge=1, le=100)
    model_service_circuit_open_seconds: float = Field(default=30, ge=1, le=3600)

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> Settings:
        """实现`validate_runtime_safety`流程；输入、输出和异常语义由类型标注及调用方约束。"""
        if self.model_dtype not in {"auto", "float32", "float16", "bfloat16"}:
            raise ValueError("MODEL_DTYPE must be auto, float32, float16 or bfloat16")
        if self.auth_mode == "local" and self.app_env.lower() not in {"dev", "development", "local"}:
            raise ValueError("AUTH_MODE=local is only allowed in development environments")
        if self.app_env.lower() in {"prod", "production"}:
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false in production")
            if self.auth_mode == "local":
                raise ValueError("AUTH_MODE=local is not allowed in production")
            if self.auth_mode == "local" and self.allow_insecure_local_auth:
                raise ValueError("ALLOW_INSECURE_LOCAL_AUTH is not allowed in production")
        if self.milvus_hybrid_search_enabled:
            total_weight = self.milvus_dense_weight + self.milvus_sparse_weight
            if total_weight <= 0:
                raise ValueError("MILVUS Dense and Sparse weights cannot both be zero")
        if (
            self.app_env.lower() in {"dev", "development", "local"}
            and str(self.local_storage_path) == "/data/files"
            and not Path("/.dockerenv").exists()
        ):
            # Docker mounts /data/files; host-side development needs a writable local fallback.
            self.local_storage_path = Path(".merchpilot-data/files")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """实现`cors_origin_list`流程；输入、输出和异常语义由类型标注及调用方约束。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def local_auth_role_list(self) -> tuple[str, ...]:
        """实现`local_auth_role_list`流程；输入、输出和异常语义由类型标注及调用方约束。"""
        roles = tuple(role.strip() for role in self.local_auth_roles.split(",") if role.strip())
        return roles or ("viewer",)

    @property
    def local_auth_profile_list(self) -> tuple[str, ...]:
        """实现`local_auth_profile_list`流程；输入、输出和异常语义由类型标注及调用方约束。"""
        profiles = tuple(
            profile.strip() for profile in self.local_auth_profiles.split(",") if profile.strip()
        )
        return profiles or ("viewer",)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """实现`get_settings`流程；输入、输出和异常语义由类型标注及调用方约束。"""
    return Settings()
