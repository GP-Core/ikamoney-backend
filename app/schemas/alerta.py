"""Esquemas de alertas, su configuración y la revisión diaria (T47, T49)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import Edicion, Entrada
from app.services.alertas_reglas import reglas_vigentes

_R = reglas_vigentes().rangos
UMBRAL_MIN, UMBRAL_MAX = _R["umbral_utilizacion"]
DIAS_MIN, DIAS_MAX = _R["dias_anticipacion"]


class AlertaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    regla: str
    severidad: str
    titulo: str
    mensaje: str
    accion: str
    referencia: str
    estado: str
    leida: bool
    creada_en: datetime
    resuelta_en: Optional[datetime]


class AlertasOut(BaseModel):
    total: int
    sin_leer: int
    alertas: list[AlertaOut]


class AlertaLeer(Entrada):
    leida: bool


class CanalesOut(BaseModel):
    correo: bool
    push: bool


class ConfiguracionOut(BaseModel):
    umbral_utilizacion: int
    dias_anticipacion: int
    canales: CanalesOut


class CanalesEditar(Edicion):
    NO_NULOS = ("correo", "push")
    correo: Optional[bool] = None
    push: Optional[bool] = None


class ConfiguracionEditar(Edicion):
    NO_NULOS = ("umbral_utilizacion", "dias_anticipacion", "canales")
    umbral_utilizacion: Optional[int] = Field(None, ge=UMBRAL_MIN, le=UMBRAL_MAX)
    dias_anticipacion: Optional[int] = Field(None, ge=DIAS_MIN, le=DIAS_MAX)
    canales: Optional[CanalesEditar] = None


class RevisionOut(BaseModel):
    usuarios_revisados: int
    alertas_nuevas: int
    alertas_resueltas: int
    avisos_enviados: int
    errores: int
