from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "linguaear-api"
    jwt_audience: str = "linguaear-app"
    access_token_minutes: int = 15
    refresh_token_days: int = 1
    remember_me_days: int = 30

    # One-time tokens (emailed links)
    verify_email_hours: int = 24
    reset_password_minutes: int = 30
    require_verified_email: bool = False  # True: login returns 403 until the email is verified

    # Email. With no smtp_host, emails are logged to the console instead of sent (dev mode).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "LinguaEar <no-reply@linguaear.app>"
    frontend_url: str = "http://localhost:8081"  # base for the links inside emails


settings = Settings()
