from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    app_env: str = "development"

    # Worker identity — set per container in docker-compose.yml.
    # Defaults to "all" for local dev where one worker handles everything.
    worker_type: str = "all"

    # Rate limiting
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60
    max_pending_jobs_per_user: int = 50

    # Uploads
    upload_dir: str = "uploads"
    max_upload_size_bytes: int = 52_428_800  # 50 MB
    upload_chunk_size: int = 8192  # 8 KB

    @property
    def async_database_url(self) -> str:
        """Derive the asyncpg URL from DATABASE_URL."""
        return self.database_url.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )

settings = Settings()
