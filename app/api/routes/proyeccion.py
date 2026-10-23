"""Endpoint de balance y proyección (T33). Solo HTTP: la lógica vive en app/services/proyeccion.py."""
from decimal import Decimal

from fastapi import APIRouter, Query

from app.api.deps import Db, UsuarioActual
from app.schemas.proyeccion import ProyeccionOut
from app.services import formulas
from app.services import proyeccion as servicio

router = APIRouter(prefix="/proyeccion", tags=["Balance y proyección"])


@router.get("", response_model=ProyeccionOut,
            summary="Balance del mes y proyección de los meses siguientes (T25, Fórmulas 1 a 3)")
def obtener(db: Db, usuario: UsuarioActual,
            meses: int = Query(formulas.HORIZONTE_DEFECTO, ge=formulas.HORIZONTE_MIN,
                               le=formulas.HORIZONTE_MAX,
                               description="Meses a proyectar, de 3 a 24 (por defecto 12)"),
            ahorro_inicial: Decimal = Query(Decimal("0"), ge=0, max_digits=12, decimal_places=2,
                                            description="Dinero disponible hoy (efectivo y débito)")):
    return servicio.calcular(db, usuario, meses, ahorro_inicial)