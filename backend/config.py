from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    vision_agent_api_key: str = ""
    cors_origins: list[str] = ["*"]
    parse_model: str = "dpt-2-latest"
    extract_model: str = "extract-latest"
    max_upload_size_mb: int = 15

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"


settings = Settings()
