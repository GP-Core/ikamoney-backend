"""Endpoint de la cuenta (T56). Solo HTTP: la lógica vive en app/services/cuenta.py."""
from fastapi import APIRouter

from app.api.deps import Db, UsuarioActual
from app.schemas.cuenta import CuentaEliminar
from app.services import cuenta as servicio

router = APIRouter(prefix="/cuenta", tags=["Cuenta"])


@router.delete("", status_code=204,
               summary="Elimina la cuenta y todos los datos del usuario (irreversible)",
               responses={403: {"description": "CONTRASENA_INCORRECTA: no se borra nada"}})
def eliminar(body: CuentaEliminar, db: Db, usuario: UsuarioActual):
    servicio.eliminar(db, usuario, body)
