from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./hipass.db"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24 * 7

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"

    storage_dir: str = "./storage"
    font_path: str | None = None

    scheduler_enabled: bool = True
    reminder_hour: int = 9

    # 기여도 가중치 (합이 1일 필요는 없음 - 자동 정규화)
    score_w_speech: float = 0.3
    score_w_task: float = 0.4
    score_w_upload: float = 0.3


settings = Settings()
