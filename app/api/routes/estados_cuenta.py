"""Carga y extracción de estados de cuenta (T31). Solo HTTP: la lógica vive en
app/services/estados_cuenta/."""
from typing import Optional

from fastapi import APIRouter, File, UploadFile

from app.api.deps import ClienteIADep, UsuarioActual
from app.schemas.estado_cuenta import EstadoCuentaExtraidoOut
from app.services import estados_cuenta as servicio

router = APIRouter(prefix="/estados-cuenta", tags=["Estados de cuenta"])


@router.post("/extraer", response_model=EstadoCuentaExtraidoOut,
             summary="Lee un estado de cuenta en PDF con IA y devuelve sus datos, sin guardar nada")
def extraer(usuario: UsuarioActual, cliente: ClienteIADep,
            archivo: Optional[UploadFile] = File(None, description="Estado de cuenta en PDF, máximo 10 MB")):
    return servicio.extraer(usuario, archivo.file if archivo else None,
                            archivo.content_type if archivo else None, cliente)
