"""Centro de notificaciones y configuración de alertas (T47, T48, T49). Solo HTTP: la lógica vive en
app/services/alertas.py."""
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.api.deps import Db, UsuarioActual
from app.schemas.alerta import (AlertaLeer, AlertaOut, AlertasOut, ConfiguracionEditar,
                                ConfiguracionOut)
from app.services import alertas as servicio

router = APIRouter(prefix="/alertas", tags=["Alertas"])
MAX_ID = 2**63 - 1   # BIGINT: un id mayor no puede existir y la base lo rechazaría con un 500


@router.get("", response_model=AlertasOut,
            summary="Alertas del usuario, más recientes primero, con el total sin leer")
def listar(db: Db, usuario: UsuarioActual,
           estado: Literal["activa", "resuelta", "todas"] = Query("activa"),
           limite: int = Query(servicio.LIMITE_DEFECTO, ge=1, le=servicio.LIMITE_MAX)):
    return servicio.listar(db, usuario, estado, limite)


# /configuracion va antes que /{alerta_id}, que es un entero
@router.get("/configuracion", response_model=ConfiguracionOut,
            summary="Umbral, días de anticipación y canales de las alertas")
def ver_configuracion(db: Db, usuario: UsuarioActual):
    return servicio.configuracion(db, usuario)


@router.put("/configuracion", response_model=ConfiguracionOut,
            summary="Cambia umbral, días de anticipación o canales (solo lo enviado) y reevalúa")
def cambiar_configuracion(datos: ConfiguracionEditar, db: Db, usuario: UsuarioActual):
    return servicio.guardar_configuracion(db, usuario, datos)


@router.patch("/{alerta_id}", response_model=AlertaOut, summary="Marca una alerta como leída o no leída")
def marcar_leida(alerta_id: Annotated[int, Path(ge=1, le=MAX_ID)], datos: AlertaLeer, db: Db, usuario: UsuarioActual):
    return servicio.marcar_leida(db, usuario, alerta_id, datos.leida)
