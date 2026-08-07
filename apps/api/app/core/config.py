from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Maritime Claims & Risk Intelligence Platform"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://maritime:change-me@localhost:5432/maritime_claims"
    secret_key: str = "replace-with-a-long-random-secret"
    storage_backend: str = "local"
    local_storage_path: str = ".local-storage/documents"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
