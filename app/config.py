from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite:///./data.db"
    CERT_DIR: str = "./data/certificates"
    MAX_RECIPIENTS: int = 1000
    LOG_LEVEL: str = "INFO"


settings = Settings()
