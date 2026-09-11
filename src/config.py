"""Central configuration. Everything reads from here, nothing hardcodes a value."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/pm25"

    latitude: float = -6.2088
    longitude: float = 106.8456
    location_name: str = "Jakarta"

    lookback_hours: int = 168  # one week of history feeds the model
    horizon_hours: int = 24  # how far ahead we forecast

    model_dir: str = "models"

    # Open-Meteo endpoints. No API key required.
    air_quality_url: str = "https://air-quality-api.open-meteo.com/v1/air-quality"

    @property
    def model_path(self) -> Path:
        return Path(self.model_dir)


settings = Settings()
