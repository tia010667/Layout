"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI Provider
    ai_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Agent
    max_retries: int = 3
    upload_dir: str = "uploads"
    output_dir: str = "output"

    # File size limits (bytes)
    max_template_size: int = 10 * 1024 * 1024    # 10 MB
    max_content_size: int = 10 * 1024 * 1024     # 10 MB

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
