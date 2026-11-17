"""Esquemas de /auth (T51). Contrato fijado por el frontend (src/types/auth.ts)."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.base import Entrada

_PATRON_CORREO = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")  # el mismo que valida el frontend
_LETRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
_NUMERO = re.compile(r"\d")

CONTRASENA_MIN, CONTRASENA_MAX = 8, 64


def _validar_correo(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 255 or not _PATRON_CORREO.match(v):
        raise ValueError("Escribe un correo válido, por ejemplo nombre@correo.com.")
    return v


def _validar_contrasena_nueva(v: str) -> str:
    if len(v) < CONTRASENA_MIN or len(v) > CONTRASENA_MAX:
        raise ValueError(f"Debe tener de {CONTRASENA_MIN} a {CONTRASENA_MAX} caracteres.")
    if not _LETRA.search(v) or not _NUMERO.search(v):
        raise ValueError("Debe incluir al menos una letra y un número.")
    return v


class _EntradaContrasena(Entrada):
    # La contraseña se compara tal cual: no se recortan los espacios (Entrada sí lo hace).
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class RegistroEntrada(_EntradaContrasena):
    nombre: str
    correo: str
    contrasena: str
    acepta_terminos: bool

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v: str) -> str:
        v = v.strip()
        if not 2 <= len(v) <= 100:
            raise ValueError("Debe tener de 2 a 100 caracteres.")
        return v

    @field_validator("correo")
    @classmethod
    def _correo(cls, v: str) -> str:
        return _validar_correo(v)

    @field_validator("contrasena")
    @classmethod
    def _contrasena(cls, v: str) -> str:
        return _validar_contrasena_nueva(v)


class LoginEntrada(_EntradaContrasena):
    correo: str
    contrasena: str

    @field_validator("correo")
    @classmethod
    def _correo(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("contrasena")
    @classmethod
    def _contrasena(cls, v: str) -> str:
        if not 1 <= len(v) <= 128:
            raise ValueError("Escribe tu contraseña.")
        return v


class RecuperarEntrada(_EntradaContrasena):
    correo: str

    @field_validator("correo")
    @classmethod
    def _correo(cls, v: str) -> str:
        return v.strip().lower()


class RestablecerEntrada(_EntradaContrasena):
    token: str
    contrasena: str

    @field_validator("contrasena")
    @classmethod
    def _contrasena(cls, v: str) -> str:
        return _validar_contrasena_nueva(v)


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    correo: str
    moneda: str


class SesionOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expira_en: int  # segundos
    usuario: UsuarioOut


class MensajeOut(BaseModel):
    mensaje: str
    enlace_prueba: str | None = None
