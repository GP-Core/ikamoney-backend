"""Endpoints de tarjetas. Solo HTTP: la lógica vive en app/services/tarjetas.py."""
from typing import Optional

from fastapi import APIRouter, Query

from app.api.deps import Db, UsuarioActual
from app.schemas.tarjeta import (TarjetaCrear, TarjetaEditar, TarjetaEliminadaOut,
                                 TarjetaOut)
from app.services import tarjetas as servicio

router = APIRouter(prefix="/tarjetas", tags=["Tarjetas"])


@router.get("", response_model=list[TarjetaOut],
            summary="Lista con saldo, porcentaje del límite usado y próxima fecha de pago")
def listar(db: Db, usuario: UsuarioActual,
           activa: Optional[bool] = Query(None, description="Filtra por activas/inactivas")):
    return servicio.listar(db, usuario, activa)


@router.post("", response_model=TarjetaOut, status_code=201, summary="Registra una tarjeta")
def crear(body: TarjetaCrear, db: Db, usuario: UsuarioActual):
    return servicio.crear(db, usuario, body)


@router.get("/{id}", response_model=TarjetaOut, summary="Detalle de una tarjeta")
def detalle(id: int, db: Db, usuario: UsuarioActual):
    return servicio.detalle(db, usuario, id)


@router.put("/{id}", response_model=TarjetaOut,
            summary="Edita una tarjeta (solo cambia los campos enviados)")
def editar(id: int, body: TarjetaEditar, db: Db, usuario: UsuarioActual):
    return servicio.editar(db, usuario, id, body)


@router.delete("/{id}", response_model=TarjetaEliminadaOut,
               summary="Elimina la tarjeta y, en cascada, sus MSI y estados de cuenta")
def eliminar(id: int, db: Db, usuario: UsuarioActual):
    return servicio.eliminar(db, usuario, id)
