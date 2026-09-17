from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Time Tracking API"
    database_url: str = "sqlite:///./time_tracking.db"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: list[str] = ["http://localhost:3000"]
    # Render assigns each blueprint-deployed service a random hostname suffix
    # that isn't known until deploy time, so a static entry in cors_origins
    # can't name it. render.yaml instead binds this to the frontend service's
    # actual host via `fromService`/`property: host` (a bare host, no scheme).
    cors_extra_origin_host: str | None = None

    # One-time cold-start seed for the first admin account, since
    # self-registration no longer exists (see app/services/bootstrap.py).
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_name: str = "Admin"

    @property
    def effective_cors_origins(self) -> list[str]:
        if not self.cors_extra_origin_host:
            return self.cors_origins
        return [*self.cors_origins, f"https://{self.cors_extra_origin_host}"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
