from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Maritime Claims & Risk Intelligence Platform"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://maritime:change-me@localhost:5432/maritime_claims"
    secret_key: str = "replace-with-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    token_issuer: str = "mcri-api"
    token_audience: str = "mcri-web"
    auth_cookie_name: str = "mcri_access_token"
    cors_allowed_origins: str = "http://localhost:3000"
    storage_backend: str = "local"
    local_storage_path: str = ".local-storage/documents"
    max_upload_mb: int = 25
    malware_scan_enabled: bool = False
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0
    processing_max_attempts: int = 3
    processing_poll_seconds: float = 2.0
    ocr_enabled: bool = False
    ocr_languages: str = "eng+fas"
    ocr_max_pages: int = 20
    ocr_timeout_seconds: float = 120.0
    ai_provider: str = "disabled"
    ai_model: str = ""
    openai_api_key: str = ""
    ai_max_input_chars: int = 60000
    ai_max_output_tokens: int = 2000
    ai_prompt_bundle_version: str = "2026-08-20.1"
    ai_schema_bundle_version: str = "2026-08-20.1"
    allow_external_ai_restricted: bool = False

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
