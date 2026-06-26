from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ClickUp
    clickup_api_token: str
    clickup_webhook_secret: str = ""
    clickup_team_id: str
    clickup_default_space_id: str = ""

    # Airbox (AltoQI Visus Workflow)
    airbox_api_key: str
    airbox_base_url: str = "https://api.airbox.tech"
    # Tipo da entidade ao criar tasks no Airbox (API real usa "Agreement")
    airbox_default_entity_type: str = "Agreement"

    # Database
    database_url: str = "sqlite+aiosqlite:///./sync.db"

    # App
    app_env: str = "development"
    app_port: int = 8000
    log_level: str = "INFO"

    # Sync
    polling_interval_seconds: int = 60
    sync_enabled: bool = True

    # Dashboard / Cache
    cache_refresh_interval_seconds: int = 300
    cache_refresh_on_startup: bool = True
    dashboard_enabled: bool = True
    sse_keepalive_seconds: float = 15.0

    # Chat / AI Agent
    chat_enabled: bool = True
    anthropic_api_key: str = ""
    chat_model: str = "claude-haiku-4-5-20251001"
    chat_max_iterations: int = 5
    chat_max_tokens: int = 1024


settings = Settings()
