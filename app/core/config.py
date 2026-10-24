from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env vive en la raíz del repo (una carpeta arriba de backend/)
ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    database_url: str
    # Texto separado por comas (no lista): así CORS_ORIGINS se escribe en el .env sin formato JSON
    cors_origins: str = "http://localhost:5173,https://ikamoney-dun.vercel.app"
    ai_api_key: str = ""

    # --- Autenticación (T17: JWT, vence en 24 h) ---
    jwt_secret: str = "cambia_esto_en_produccion"
    jwt_algorithm: str = "HS256"
    jwt_horas: int = 24

    # --- Reglas de negocio ---
    zona_horaria: str = "America/Mexico_City"
    max_mensualidades: int = 60  # tope razonable para MSI (T18 solo fija el mínimo: 2)

    # --- Estados de cuenta con IA (T31; valores probados en la PoC de T08) ---
    ia_modelo: str = "gemini-3.1-flash-lite"
    ia_limite_s: float = 30       # tope de la llamada a la IA, con reintentos incluidos (IS-04)
    ia_reintentos_json: int = 3   # reintentos si la IA no responde un JSON válido
    pdf_max_mb: int = 10

    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()