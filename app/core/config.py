from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env vive en la raíz del repo (una carpeta arriba de backend/)
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    database_url: str
    cors_origins: str = "http://localhost:5173"
    ai_api_key: str = ""

    # --- Autenticación (T17: JWT, vence en 24 h) ---
    jwt_secret: str = "cambia_esto_en_produccion"
    jwt_algorithm: str = "HS256"
    jwt_horas: int = 24

    # --- Reglas de negocio ---
    zona_horaria: str = "America/Mexico_City"
    max_mensualidades: int = 60  # tope razonable para MSI (T18 solo fija el mínimo: 2)

    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()