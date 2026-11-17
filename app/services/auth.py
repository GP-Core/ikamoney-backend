"""Registro, inicio de sesión y recuperación de contraseña (T51).

Se confirma con `db.commit()` y no con `comunes.confirmar()`: recalcular() guardaría un score
de un usuario sin datos (mismo motivo que en services/cuenta.py).
"""
from functools import cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import ApiError, campo_error
from app.core.seguridad import (crear_token, crear_token_recuperacion, hash_contrasena,
                                huella_contrasena, leer_token_recuperacion, verificar_contrasena)
from app.models import Usuario
from app.schemas.auth import (LoginEntrada, MensajeOut, RecuperarEntrada, RegistroEntrada,
                              RestablecerEntrada, SesionOut)

MENSAJE_RECUPERACION = "Si el correo está registrado, te enviamos un enlace para restablecer tu contraseña."


@cache
def _hash_senuelo() -> str:
    # Para que un correo inexistente tarde lo mismo que uno existente con contraseña incorrecta.
    return hash_contrasena("senuelo-sin-usuario")


def _sesion(usuario: Usuario) -> SesionOut:
    return SesionOut(access_token=crear_token(usuario.id), expira_en=settings.jwt_horas * 3600,
                     usuario=usuario)


def _por_correo(db: Session, correo: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.correo == correo))


def _correo_repetido() -> ApiError:
    return ApiError(409, "CORREO_YA_REGISTRADO", "Ya existe una cuenta con ese correo.",
                    [campo_error("correo", "Ya está registrado.")])


def registrar(db: Session, datos: RegistroEntrada) -> SesionOut:
    if not datos.acepta_terminos:
        raise ApiError(422, "TERMINOS_NO_ACEPTADOS",
                       "Debes aceptar el aviso de privacidad y los términos de uso.",
                       [campo_error("acepta_terminos", "Debes aceptar para crear la cuenta.")])
    if _por_correo(db, datos.correo) is not None:
        raise _correo_repetido()
    usuario = Usuario(nombre=datos.nombre, correo=datos.correo,
                      contrasena_hash=hash_contrasena(datos.contrasena), moneda="MXN")
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError:   # dos registros simultáneos con el mismo correo
        db.rollback()
        raise _correo_repetido()
    db.refresh(usuario)
    return _sesion(usuario)


def iniciar_sesion(db: Session, datos: LoginEntrada) -> SesionOut:
    usuario = _por_correo(db, datos.correo)
    hash_guardado = usuario.contrasena_hash if usuario else _hash_senuelo()
    valida = verificar_contrasena(datos.contrasena, hash_guardado)
    if usuario is None or not valida:
        # Mismo error exista o no el correo (REQ-CU-04).
        raise ApiError(401, "CREDENCIALES_INVALIDAS", "Correo o contraseña incorrectos.")
    return _sesion(usuario)


def solicitar_recuperacion(db: Session, datos: RecuperarEntrada) -> MensajeOut:
    respuesta = MensajeOut(mensaje=MENSAJE_RECUPERACION)
    usuario = _por_correo(db, datos.correo)
    if usuario is not None and settings.recuperacion_enlace_prueba:
        token = crear_token_recuperacion(usuario)
        respuesta.enlace_prueba = f"{settings.frontend_url.rstrip('/')}/restablecer-contrasena?token={token}"
    # Con correo real (T50) aquí se enviaría el enlace; la respuesta no cambia.
    return respuesta


def restablecer(db: Session, datos: RestablecerEntrada) -> None:
    invalido = ApiError(400, "ENLACE_INVALIDO", "El enlace no es válido o ya expiró.")
    leido = leer_token_recuperacion(datos.token)
    if leido is None:
        raise invalido
    usuario_id, huella = leido
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or huella != huella_contrasena(usuario.contrasena_hash):
        raise invalido
    usuario.contrasena_hash = hash_contrasena(datos.contrasena)   # la huella cambia: enlace de un solo uso
    db.commit()
