"""Acceso (T51). Solo HTTP: la lógica vive en app/services/auth.py. Va bajo /api/auth (no /api/v1)."""
from fastapi import APIRouter

from app.api.deps import Db, UsuarioActual
from app.schemas.auth import (LoginEntrada, MensajeOut, RecuperarEntrada, RegistroEntrada,
                              RestablecerEntrada, SesionOut, UsuarioOut)
from app.services import auth as servicio

router = APIRouter(prefix="/auth", tags=["Acceso"])


@router.post("/registro", response_model=SesionOut, status_code=201,
             summary="Crea la cuenta y abre sesión",
             responses={409: {"description": "CORREO_YA_REGISTRADO"},
                        422: {"description": "TERMINOS_NO_ACEPTADOS o datos inválidos"}})
def registro(body: RegistroEntrada, db: Db):
    return servicio.registrar(db, body)


@router.post("/login", response_model=SesionOut, summary="Abre sesión",
             responses={401: {"description": "CREDENCIALES_INVALIDAS (igual exista o no el correo)"}})
def login(body: LoginEntrada, db: Db):
    return servicio.iniciar_sesion(db, body)


@router.get("/me", response_model=UsuarioOut, summary="Usuario del token (valida la sesión)")
def me(usuario: UsuarioActual):
    return usuario


@router.post("/logout", status_code=204,
             summary="Cierra sesión (los tokens no se revocan; el cliente lo descarta)")
def logout():
    return None


@router.post("/recuperar-contrasena", response_model=MensajeOut, response_model_exclude_none=True,
             summary="Solicita el enlace de recuperación (misma respuesta exista o no el correo)")
def recuperar(body: RecuperarEntrada, db: Db):
    return servicio.solicitar_recuperacion(db, body)


@router.post("/restablecer-contrasena", status_code=204,
             summary="Cambia la contraseña con el token de recuperación",
             responses={400: {"description": "ENLACE_INVALIDO"}})
def restablecer(body: RestablecerEntrada, db: Db):
    servicio.restablecer(db, body)
