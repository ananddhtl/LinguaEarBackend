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


settings = Settings()
