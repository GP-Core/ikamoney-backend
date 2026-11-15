"""Esquemas de /cuenta (T56)."""
from pydantic import ConfigDict, Field

from app.schemas.base import Entrada


class CuentaEliminar(Entrada):
    # La contraseña se compara tal cual: aquí no se recortan los espacios (Entrada sí lo hace).
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    contrasena: str = Field(min_length=1, max_length=128)
