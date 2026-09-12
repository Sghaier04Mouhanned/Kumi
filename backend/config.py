from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_origins: list[str] = ["*"]
    max_upload_size_mb: int = 15

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # Gates POST /api/catalog (publishing the shared timetable everyone
    # loads by default). Empty means publishing is disabled entirely --
    # fail closed, never fail open.
    admin_token: str = ""


settings = Settings()
