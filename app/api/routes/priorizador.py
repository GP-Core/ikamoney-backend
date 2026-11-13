"""Endpoint del priorizador de deudas (T43) y su plan de pagos (T45). Solo HTTP: la lógica vive
en app/services/priorizador.py y app/services/plan_pagos.py."""
from decimal import Decimal

from fastapi import APIRouter, Query

from app.api.deps import Db, UsuarioActual
from app.schemas.priorizador import PriorizadorOut
from app.services import priorizador as servicio

router = APIRouter(prefix="/priorizador", tags=["Priorizador de deudas"])


@router.get("", response_model=PriorizadorOut,
            summary="Deudas ordenadas por costo real, con la razón de cada posición, y plan de "
                    "pagos con el ahorro estimado (T25, Fórmulas 9 y 10)")
def obtener(db: Db, usuario: UsuarioActual,
            extra_mensual: Decimal = Query(Decimal("0"), ge=0, max_digits=12, decimal_places=2,
                                           description="Dinero extra al mes para abonar a las "
                                                       "deudas, además de los mínimos")):
    return servicio.priorizar(db, usuario, extra_mensual)