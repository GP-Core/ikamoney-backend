"""Token JWT (T17 §3): el usuario sale del token; nunca del cuerpo ni de la URL.

El módulo /auth (T51) emite los tokens con settings.jwt_secret (campo `sub` = id del usuario);
usuario_actual los valida. Los tokens de recuperación de contraseña llevan `uso` y no sirven de sesión.
"""
import hashlib
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errores import ApiError
from app.models import Usuario

_bearer = HTTPBearer(auto_error=False)  # auto_error=False => respondemos 401 con nuestro formato
_hasher = PasswordHasher()  # Argon2id con los parámetros por defecto de argon2-cffi


def hash_contrasena(contrasena: str) -> str:
    """Hash Argon2id para guardar en usuario.contrasena_hash. Nunca se guarda la contraseña."""
    return _hasher.hash(contrasena)


def verificar_contrasena(contrasena: str, hash_guardado: str) -> bool:
    """True si la contraseña corresponde al hash. Un hash que no es Argon2 (p. ej. el "x" de los
    usuarios de prueba) no coincide con ninguna contraseña."""
    try:
        return _hasher.verify(hash_guardado, contrasena)
    except (VerificationError, InvalidHashError):
        return False


def crear_token(usuario_id: int, horas: int | None = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=horas or settings.jwt_horas)
    return jwt.encode({"sub": str(usuario_id), "exp": exp}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def huella_contrasena(hash_guardado: str) -> str:
    """Resumen corto del hash vigente: al cambiar la contraseña deja de coincidir (enlace de un solo uso)."""
    return hashlib.sha256(hash_guardado.encode()).hexdigest()[:16]


def crear_token_recuperacion(usuario: Usuario) -> str:
    """JWT de recuperación (vence en settings.recuperacion_minutos). No sirve como sesión."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.recuperacion_minutos)
    return jwt.encode({"sub": str(usuario.id), "uso": "recuperacion",
                       "huella": huella_contrasena(usuario.contrasena_hash), "exp": exp},
                      settings.jwt_secret, algorithm=settings.jwt_algorithm)


def leer_token_recuperacion(token: str) -> tuple[int, str] | None:
    """(usuario_id, huella) si el token es de recuperación y vigente; si no, None."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("uso") != "recuperacion":
            return None
        return int(payload["sub"]), str(payload["huella"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def usuario_actual(cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
                   db: Session = Depends(get_db)) -> Usuario:
    if cred is None:
        raise ApiError(401, "NO_AUTENTICADO", "Inicia sesión para continuar.")
    try:
        payload = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if "uso" in payload:   # token de recuperación: no es una sesión
            raise ValueError
        usuario_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise ApiError(401, "TOKEN_INVALIDO", "La sesión venció o no es válida.")
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise ApiError(401, "TOKEN_INVALIDO", "La sesión venció o no es válida.")
    return usuario
