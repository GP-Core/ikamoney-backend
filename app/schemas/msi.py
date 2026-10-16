"""Esquemas de /msi (T17 §4.3)."""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.base import Dinero, Edicion, Entrada


class MsiCrear(Entrada):
    tarjeta_id: int = Field(ge=1)
    categoria_id: Optional[int] = Field(default=None, ge=1)
    descripcion: str = Field(min_length=1, max_length=120)
    monto_original: Dinero = Field(gt=0)
    num_mensualidades: int = Field(ge=2, le=settings.max_mensualidades)
    mensualidades_pagadas: int = Field(default=0, ge=0)
    # Si no se manda, se calcula: monto_original / num_mensualidades (redondeo a centavos)
    monto_mensualidad: Optional[Dinero] = Field(default=None, gt=0)
    fecha_compra: date


class MsiEditar(Edicion):
    NO_NULOS = ("tarjeta_id", "descripcion", "monto_original", "num_mensualidades",
                "mensualidades_pagadas", "monto_mensualidad", "fecha_compra", "estatus")
    tarjeta_id: Optional[int] = Field(default=None, ge=1)
    categoria_id: Optional[int] = Field(default=None, ge=1)
    descripcion: Optional[str] = Field(default=None, min_length=1, max_length=120)
    monto_original: Optional[Dinero] = Field(default=None, gt=0)
    num_mensualidades: Optional[int] = Field(default=None, ge=2, le=settings.max_mensualidades)
    mensualidades_pagadas: Optional[int] = Field(default=None, ge=0)
    monto_mensualidad: Optional[Dinero] = Field(default=None, gt=0)
    fecha_compra: Optional[date] = None
    # 'liquidado' no se puede mandar: lo pone el servidor cuando pagadas == total.
    estatus: Optional[Literal["activo", "cancelado"]] = None


class MsiOut(BaseModel):
    id: int
    tarjeta_id: int
    categoria_id: Optional[int]
    descripcion: str
    monto_original: Dinero
    num_mensualidades: int
    mensualidades_pagadas: int
    mensualidades_restantes: int          # derivado: total - pagadas
    monto_mensualidad: Dinero
    saldo_pendiente: Dinero               # derivado: restantes × mensualidad
    fecha_compra: date
    estatus: str
    origen: str
