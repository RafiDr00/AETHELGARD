"""
Aethelgard — FastAPI Interfacenagement

Centralized configuration using Pydantic Settings with environment variable binding.
Supports hierarchical configuration for all platform subsystems.
"""

from __future__ import annotations

import os
import tempfile
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class RedisConfig(BaseSettings):
    """Redis / Event Bus configuration."""
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    stream_max_len: int = 10000
    consumer_group: str = "aethelgard-agents"
    consumer_block_ms: int = 5000
    retry_on_timeout: bool = True
    socket_timeout: int = 30
    connection_pool_size: int = 20

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class LLMConfig(BaseSettings):
    """LLM / AI configuration."""
    model_config = SettingsConfigDict(env_prefix="OPENAI_")

    provider: str = "openai"
    api_key: str = ""
    model: str = "gpt-4"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    temperature: float = 0.1
    max_tokens: int = 4096
    request_timeout: int = 60
    max_retries: int = 3


class VectorStoreConfig(BaseSettings):
    """FAISS Vector Store configuration."""

    faiss_index_path: str = "./data/faiss_index"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    similarity_top_k: int = 5
    similarity_threshold: float = 0.7


class SandboxConfig(BaseSettings):
    """Sandbox execution environment configuration."""
    model_config = SettingsConfigDict(env_prefix="SANDBOX_")

    image: str = "aethelgard-sandbox:v1"
    timeout: int = 30
    memory_limit: str = "256m"
    cpu_limit: float = 0.5
    network_disabled: bool = True
    read_only_rootfs: bool = True
    max_concurrent: int = 3
    workspace_path: str = str(Path(tempfile.gettempdir()) / "aethelgard-sandbox")


class KubernetesConfig(BaseSettings):
    """Kubernetes deployment configuration."""
    model_config = SettingsConfigDict(env_prefix="KUBE_")

    config_path: str = "~/.kube/config"
    namespace: str = "aethelgard"
    context: Optional[str] = None
    deployment_timeout: int = 300
    health_check_interval: int = 10
    rollback_on_failure: bool = True
    max_surge: str = "25%"
    max_unavailable: str = "25%"


class AWSConfig(BaseSettings):
    """AWS cloud simulation configuration."""
    model_config = SettingsConfigDict(env_prefix="AWS_")

    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = "us-east-1"
    s3_bucket: str = "aethelgard-artifacts"


class MetricsConfig(BaseSettings):
    """Metrics engine configuration."""

    metrics_retention_days: int = 90
    engineer_hourly_cost: float = 95.0
    metrics_export_interval: int = 60
    prometheus_port: int = 9090


class AgentConfig(BaseSettings):
    """Agent orchestration configuration."""

    agent_max_retries: int = 3
    agent_timeout: int = 120
    risk_threshold_auto_deploy: float = 0.3
    risk_threshold_supervised: float = 0.7
    react_max_iterations: int = 10
    detection_sensitivity: float = 0.85
    diagnosis_confidence_threshold: float = 0.75


class DedupConfig(BaseSettings):
    """Pipeline deduplication configuration."""
    model_config = SettingsConfigDict(env_prefix="DEDUP_")

    # 120s: prevents persistent incidents from re-triggering immediately after
    # a pipeline completes. Configurable via DEDUP_FINGERPRINT_TTL_SECONDS env var.
    fingerprint_ttl_seconds: float = 120.0


class Settings(BaseSettings):
    """
    Root configuration container for Aethelgard.
    Aggregates all subsystem configurations.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "aethelgard"
    app_env: Environment = Environment.DEVELOPMENT
    app_version: str = "1.0.0"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, env="PORT")
    log_level: str = "INFO"

    # --- Subsystem Configs ---
    redis: RedisConfig = Field(default_factory=RedisConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    kubernetes: KubernetesConfig = Field(default_factory=KubernetesConfig)
    aws: AWSConfig = Field(default_factory=AWSConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    agents: AgentConfig = Field(default_factory=AgentConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)

    @property
    def is_production(self) -> bool:
        return self.app_env == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.app_env == Environment.DEVELOPMENT

    @property
    def project_root(self) -> Path:
        return Path(__file__).parent.parent

    @property
    def data_dir(self) -> Path:
        path = self.project_root / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def logs_dir(self) -> Path:
        path = self.project_root / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache()
def get_settings() -> Settings:
    """Singleton settings factory with caching."""
    return Settings()
