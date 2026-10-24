"""Cliente de IA intercambiable. Para cambiar de proveedor: otra clase que cumpla ClienteIA y
devolverla en obtener_cliente_ia()."""
from functools import lru_cache

from app.core.config import settings
from app.services.ia.base import ClienteIA, IaNoDisponible
from app.services.ia.gemini import GeminiCliente

__all__ = ["ClienteIA", "IaNoDisponible", "obtener_cliente_ia"]


@lru_cache
def obtener_cliente_ia() -> ClienteIA:
    """Cliente compartido por todas las peticiones (dependencia de FastAPI)."""
    return GeminiCliente(api_key=settings.ai_api_key, modelo=settings.ia_modelo)
