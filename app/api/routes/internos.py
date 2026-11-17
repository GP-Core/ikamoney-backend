"""Rutas internas que llama el cron, no la app (T47/T50). Van protegidas con llave secreta, no con JWT."""
import hmac
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header

from app.api.deps import Db
from app.core.config import settings
from app.core.errores import ApiError
from app.schemas.alerta import RevisionOut
from app.services import alertas as servicio

router = APIRouter(prefix="/internos", tags=["Internos"])


def _verificar_llave(x_llave_interna: Annotated[Optional[str], Header()] = None) -> None:
    if not settings.cron_secret:   # sin llave configurada la ruta queda cerrada
        raise ApiError(503, "CRON_NO_CONFIGURADO", "La revisión diaria no está habilitada.")
    if not x_llave_interna or not hmac.compare_digest(x_llave_interna.encode(),
                                                      settings.cron_secret.encode()):
        raise ApiError(401, "LLAVE_INVALIDA", "Llave interna no válida.")


@router.post("/revision-diaria", response_model=RevisionOut,
             summary="Revisa las alertas de todos los usuarios (la llama el cron, con X-Llave-Interna)")
def revision_diaria(db: Db, _: Annotated[None, Depends(_verificar_llave)]):
    return servicio.revision_diaria(db)
