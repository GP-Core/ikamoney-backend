"""Esquemas de /deudas (T17 §4.3)."""
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.base import Dia, Dinero, Edicion, Entrada, Tasa


TipoDeuda = Literal["prestamo_personal", "credito_auto", "credito_hipotecario",
                    "familiar_amigo", "otro"]


class DeudaCrear(Entrada):
    nombre: str = Field(min_length=1, max_length=100)
    acreedor: Optional[str] = Field(default=None, min_length=1, max_length=100)
    tipo: TipoDeuda
    monto_original: Dinero = Field(gt=0)
    saldo_actual: Dinero = Field(ge=0)
    tasa_anual: Optional[Tasa] = Field(default=None, ge=0, le=Decimal("999.99"))
    pago_mensual: Optional[Dinero] = Field(default=None, gt=0)
    dia_pago: Optional[Dia] = None
    fecha_inicio: Optional[date] = None


class DeudaEditar(Edicion):
    NO_NULOS = ("nombre", "tipo", "monto_original", "saldo_actual")
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    acreedor: Optional[str] = Field(default=None, min_length=1, max_length=100)
    tipo: Optional[TipoDeuda] = None
    monto_original: Optional[Dinero] = Field(default=None, gt=0)
    saldo_actual: Optional[Dinero] = Field(default=None, ge=0)
    tasa_anual: Optional[Tasa] = Field(default=None, ge=0, le=Decimal("999.99"))
    pago_mensual: Optional[Dinero] = Field(default=None, gt=0)
    dia_pago: Optional[Dia] = None
    fecha_inicio: Optional[date] = None


class DeudaOut(BaseModel):
    id: int
    nombre: str
    acreedor: Optional[str]
    tipo: str
    monto_original: Dinero
    saldo_actual: Dinero
    tasa_anual: Optional[Tasa]
    pago_mensual: Optional[Dinero]
    dia_pago: Optional[int]
    fecha_inicio: Optional[date]
    estatus: str                              # derivado: saldo 0 => 'liquidada'
    proxima_fecha_pago: Optional[date]
