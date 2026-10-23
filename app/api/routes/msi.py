"""Endpoints de planes MSI. Solo HTTP: la lógica vive en app/services/msi.py."""
from typing import Literal, Optional

from fastapi import APIRouter, Query

from app.api.deps import Db, UsuarioActual
from app.schemas.base import EliminadoOut
from app.schemas.msi import MsiCrear, MsiEditar, MsiOut
from app.services import msi as servicio

router = APIRouter(prefix="/msi", tags=["MSI"])


@router.get("", response_model=list[MsiOut],
            summary="Compras a MSI con mensualidades pagadas y restantes")
def listar(db: Db, usuario: UsuarioActual,
           tarjeta_id: Optional[int] = Query(None, ge=1, description="Filtra por tarjeta"),
           estatus: Optional[Literal["activo", "liquidado", "cancelado"]] = Query(None)):
    return servicio.listar(db, usuario, tarjeta_id, estatus)


@router.post("", response_model=MsiOut, status_code=201,
             summary="Registra una compra a MSI ligada a una tarjeta")
def crear(body: MsiCrear, db: Db, usuario: UsuarioActual):
    return servicio.crear(db, usuario, body)


@router.get("/{id}", response_model=MsiOut, summary="Detalle de una compra a MSI")
def detalle(id: int, db: Db, usuario: UsuarioActual):
    return servicio.detalle(db, usuario, id)


@router.put("/{id}", response_model=MsiOut,
            summary="Edita una compra a MSI (p. ej. mensualidades pagadas)")
def editar(id: int, body: MsiEditar, db: Db, usuario: UsuarioActual):
    return servicio.editar(db, usuario, id, body)


@router.delete("/{id}", response_model=EliminadoOut, summary="Elimina una compra a MSI")
def eliminar(id: int, db: Db, usuario: UsuarioActual):
    return servicio.eliminar(db, usuario, id)
