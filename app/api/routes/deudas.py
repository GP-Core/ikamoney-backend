"""Endpoints de deudas. Solo HTTP: la lógica vive en app/services/deudas.py."""
from typing import Literal, Optional

from fastapi import APIRouter, Query

from app.api.deps import Db, UsuarioActual
from app.schemas.base import EliminadoOut
from app.schemas.deuda import DeudaCrear, DeudaEditar, DeudaOut
from app.services import deudas as servicio

router = APIRouter(prefix="/deudas", tags=["Deudas"])


@router.get("", response_model=list[DeudaOut], summary="Préstamos y créditos con saldo y próximo pago")
def listar(db: Db, usuario: UsuarioActual,
           estatus: Optional[Literal["activa", "liquidada"]] = Query(None)):
    return servicio.listar(db, usuario, estatus)


@router.post("", response_model=DeudaOut, status_code=201, summary="Registra otra deuda")
def crear(body: DeudaCrear, db: Db, usuario: UsuarioActual):
    return servicio.crear(db, usuario, body)


@router.get("/{id}", response_model=DeudaOut, summary="Detalle de una deuda")
def detalle(id: int, db: Db, usuario: UsuarioActual):
    return servicio.detalle(db, usuario, id)


@router.put("/{id}", response_model=DeudaOut,
            summary="Edita una deuda (solo cambia los campos enviados)")
def editar(id: int, body: DeudaEditar, db: Db, usuario: UsuarioActual):
    return servicio.editar(db, usuario, id, body)


@router.delete("/{id}", response_model=EliminadoOut, summary="Elimina una deuda")
def eliminar(id: int, db: Db, usuario: UsuarioActual):
    return servicio.eliminar(db, usuario, id)
