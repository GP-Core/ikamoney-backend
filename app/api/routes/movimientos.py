"""Endpoints de ingresos y gastos. Solo HTTP: la lógica vive en app/services/movimientos.py."""
from typing import Literal, Optional

from fastapi import APIRouter, Query

from app.api.deps import Db, UsuarioActual
from app.schemas.movimiento import (ListaMesOut, MovimientoCrear, MovimientoEditar,
                                    MovimientoEliminadoOut, MovimientoOut)
from app.services import movimientos as servicio

router = APIRouter(prefix="/movimientos", tags=["Ingresos y gastos"])


@router.get("", response_model=ListaMesOut,
            summary="Ingresos y gastos del mes con totales (incluye los recurrentes)")
def listar(db: Db, usuario: UsuarioActual,
           mes: Optional[str] = Query(None, pattern=r"^20\d{2}-(0[1-9]|1[0-2])$",
                                      description="AAAA-MM; por defecto, el mes actual"),
           tipo: Optional[Literal["ingreso", "gasto"]] = Query(None),
           categoria_id: Optional[int] = Query(None, ge=1, description="Solo gastos de esa categoría")):
    return servicio.listar_mes(db, usuario, mes, tipo, categoria_id)


@router.post("", response_model=MovimientoOut, status_code=201,
             summary="Registra un ingreso o un gasto (fijo o variable)")
def crear(body: MovimientoCrear, db: Db, usuario: UsuarioActual):
    return servicio.crear(db, usuario, body)


@router.put("/{id}", response_model=MovimientoOut,
            summary="Edita un movimiento (solo cambia los campos enviados)")
def editar(id: str, body: MovimientoEditar, db: Db, usuario: UsuarioActual):
    return servicio.editar(db, usuario, id, body)


@router.delete("/{id}", response_model=MovimientoEliminadoOut, summary="Elimina un movimiento")
def eliminar(id: str, db: Db, usuario: UsuarioActual):
    return servicio.eliminar(db, usuario, id)
