from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    app_env: str = "development"

    # Rate limiting
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60
    max_pending_jobs_per_user: int = 50

    # Uploads
    upload_dir: str = "uploads"
    max_upload_size_bytes: int = 52_428_800  # 50 MB
    upload_chunk_size: int = 8192  # 8 KB — classic buffer size

    # Asynchronous database URL property
    @property
    def async_database_url(self) -> str:
        """
        Convert postgresql://... to postgresql+asyncpg://...
        Python Internals Focus:
        -----------------------
        @property is a descriptor — it makes a method behave like an attribute.
        Under the hood, property() returns a descriptor object with __get__.
        When you access settings.async_database_url, Python calls __get__,
        which calls our method. No parentheses needed at the call site.
        Why not store a second env var?
        One source of truth (DATABASE_URL). We derive the async version.
        """
        return self.database_url.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )

settings = Settings()
