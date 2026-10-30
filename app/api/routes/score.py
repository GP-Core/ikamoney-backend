"""Endpoints del Índice de Salud Financiera (T35). Solo HTTP: la lógica vive en app/services/score.py."""
from fastapi import APIRouter, Query

from app.api.deps import Db, UsuarioActual
from app.schemas.score import HistorialOut, ScoreOut
from app.services import score as servicio

router = APIRouter(prefix="/score", tags=["Score"])


@router.get("", response_model=ScoreOut,
            summary="Score de 0 a 100, nivel y desglose por factor (o los datos que faltan)")
def obtener(db: Db, usuario: UsuarioActual):
    return servicio.calcular(db, usuario)


@router.get("/historial", response_model=HistorialOut,
            summary="Último score de cada mes, del más antiguo al más reciente")
def historial(db: Db, usuario: UsuarioActual,
              meses: int = Query(servicio.HISTORIAL_DEFECTO, ge=1, le=servicio.HISTORIAL_MAX,
                                 description="Meses hacia atrás, incluido el actual (1 a 24)")):
    return servicio.historial(db, usuario, meses)