"""
config.py — Centralised settings loaded from .env
All services (LLM, PostgreSQL, Redis, Langfuse) are configured here.
"""

from pydantic_settings import BaseSettings
from pydantic import Field, computed_field


class Settings(BaseSettings):
    # ----------------------------------------------------------------
    # LLM Provider
    # ----------------------------------------------------------------
    LLM_PROVIDER: str = Field("groq", description="groq | google | ollama")

    # Groq
    GROQ_API_KEY: str = Field("", description="Get free key at console.groq.com")
    GROQ_MODEL: str = Field("llama-3.1-8b-instant")

    # Google Gemini
    GOOGLE_API_KEY: str = Field("", description="Get free key at aistudio.google.com")
    GOOGLE_MODEL: str = Field("gemini-1.5-flash")

    # Ollama (local)
    OLLAMA_BASE_URL: str = Field("http://localhost:11434")
    OLLAMA_MODEL: str = Field("llama3.2")

    # ----------------------------------------------------------------
    # PostgreSQL — Long-Term Memory (LTM)
    # ----------------------------------------------------------------
    POSTGRES_USER: str = Field("postgres")
    POSTGRES_PASSWORD: str = Field("postgres123")
    POSTGRES_HOST: str = Field("127.0.0.1")   # explicit IPv4 — avoids ::1 on Windows
    POSTGRES_PORT: int = Field(5433)           # 5433 avoids conflict with local Postgres
    POSTGRES_AGENT_DB: str = Field("agent_memory")

    @computed_field
    @property
    def POSTGRES_URL(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_AGENT_DB}"
        )

    # ----------------------------------------------------------------
    # Redis — Short-Term Memory (STM)
    # ----------------------------------------------------------------
    REDIS_HOST: str = Field("127.0.0.1")   # explicit IPv4 — avoids ::1 on Windows
    REDIS_PORT: int = Field(6379)
    REDIS_PASSWORD: str = Field("redis123")
    REDIS_DB: int = Field(0)
    SESSION_TTL: int = Field(3600, description="Session TTL in seconds (default 1h)")

    # ----------------------------------------------------------------
    # Langfuse Observability
    # ----------------------------------------------------------------
    LANGFUSE_PUBLIC_KEY: str = Field("", description="From Langfuse project settings")
    LANGFUSE_SECRET_KEY: str = Field("", description="From Langfuse project settings")
    LANGFUSE_HOST: str = Field("http://localhost:3000")

    @computed_field
    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
