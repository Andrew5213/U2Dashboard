import os
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("APP_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
    )

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

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        """Railway (e outros hosts) fornecem a URL do Postgres como 'postgres://' ou
        'postgresql://', sem driver async. Normaliza para 'postgresql+asyncpg://'
        para funcionar com o SQLAlchemy async engine sem exigir configuração manual."""
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

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

    # Civil works — uploads directory for photos
    civil_uploads_dir: str = "./uploads"

    # Email (relatórios semanais automáticos)
    email_enabled: bool = False
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_user: str = ""
    email_password: str = ""  # App Password do Google (não a senha normal)
    email_from: str = ""      # ex: "U2 Broadcast Angola <email@gmail.com>"
    email_recipients: str = ""  # emails separados por vírgula
    email_report_weekday: int = 6   # 0=segunda … 6=domingo
    email_report_hour: int = 8      # hora UTC do envio


settings = Settings()
