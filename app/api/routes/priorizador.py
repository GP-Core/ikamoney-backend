"""Endpoint del priorizador de deudas (T43). Solo HTTP: la lógica vive en
app/services/priorizador.py."""
from fastapi import APIRouter

from app.api.deps import Db, UsuarioActual
from app.schemas.priorizador import PriorizadorOut
from app.services import priorizador as servicio

router = APIRouter(prefix="/priorizador", tags=["Priorizador de deudas"])


@router.get("", response_model=PriorizadorOut,
            summary="Deudas y tarjetas ordenadas por costo real, con la razón de cada posición "
                    "(T25, Fórmula 9)")
def obtener(db: Db, usuario: UsuarioActual):
    return servicio.priorizar(db, usuario)