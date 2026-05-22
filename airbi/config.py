from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App-Konfiguration. Werte überschreibbar per .env oder Umgebungsvariablen."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://airbi:airbi@localhost:5432/airbi"
    test_database_url: str = "postgresql+psycopg://airbi:airbi@localhost:5432/airbi_test"


settings = Settings()
