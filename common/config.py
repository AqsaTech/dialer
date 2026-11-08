from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str
    secret_key: str
    refresh_secret_key: str

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    reset_token_minutes: int = 15
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    max_calls_per_minute: int = 5
    max_sms_per_minute: int = 10
    max_outbound_per_day: int = 300
    blocked_prefixes: str = ""
    allowed_prefixes: str = ""
    ws_auth_timeout_seconds: int = 10

    frontend_url: str = "http://127.0.0.1:8001"
    mail_server: str | None = None
    mail_port: int = 587
    mail_username: str | None = None
    mail_password: str | None = None
    mail_from: str = "noreply@example.com"

    @property
    def blocked_prefix_list(self) -> list[str]:
        return [p.strip() for p in self.blocked_prefixes.split(",") if p.strip()]

    @property
    def allowed_prefix_list(self) -> list[str]:
        return [p.strip() for p in self.allowed_prefixes.split(",") if p.strip()]

    @model_validator(mode="after")
    def check_keys(self):
        if len(self.secret_key) < 32 or len(self.refresh_secret_key) < 32:
            raise ValueError("SECRET_KEY and REFRESH_SECRET_KEY must be at least 32 characters")
        if self.secret_key == self.refresh_secret_key:
            raise ValueError("SECRET_KEY and REFRESH_SECRET_KEY must be different")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
