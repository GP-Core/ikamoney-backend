from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env vive en la raíz del repo (una carpeta arriba de backend/)
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    database_url: str
    cors_origins: list[str] = ["http://localhost:5173","https://ikamoney-dun.vercel.app"]
    ai_api_key: str = ""

    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return self.cors_origins


settings = Settings()