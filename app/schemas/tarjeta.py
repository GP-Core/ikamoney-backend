"""Esquemas de /tarjetas (T17 §4.3)."""
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.base import Dia, Dinero, Edicion, Entrada, EliminadoOut, Tasa


class TarjetaCrear(Entrada):
    nombre: str = Field(min_length=1, max_length=60)
    banco: str = Field(min_length=1, max_length=60)
    ultimos_4: Optional[str] = Field(default=None, pattern=r"^[0-9]{4}$")  # nunca el número completo
    limite_credito: Dinero = Field(ge=0)
    saldo_actual: Dinero = Field(default=Decimal("0.00"), ge=0)
    dia_corte: Dia
    dia_pago: Dia
    tasa_anual: Optional[Tasa] = Field(default=None, ge=0, le=Decimal("999.99"))
    activa: bool = True


class TarjetaEditar(Edicion):
    NO_NULOS = ("nombre", "banco", "limite_credito", "saldo_actual", "dia_corte", "dia_pago", "activa")
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=60)
    banco: Optional[str] = Field(default=None, min_length=1, max_length=60)
    ultimos_4: Optional[str] = Field(default=None, pattern=r"^[0-9]{4}$")
    limite_credito: Optional[Dinero] = Field(default=None, ge=0)
    saldo_actual: Optional[Dinero] = Field(default=None, ge=0)
    dia_corte: Optional[Dia] = None
    dia_pago: Optional[Dia] = None
    tasa_anual: Optional[Tasa] = Field(default=None, ge=0, le=Decimal("999.99"))
    activa: Optional[bool] = None


class TarjetaOut(BaseModel):
    id: int
    nombre: str
    banco: str
    ultimos_4: Optional[str]
    limite_credito: Dinero
    saldo_actual: Dinero
    credito_disponible: Dinero            # derivado
    porcentaje_limite_usado: float        # derivado (saldo / límite × 100)
    dia_corte: int
    dia_pago: int
    tasa_anual: Optional[Tasa]
    activa: bool
    proxima_fecha_corte: date             # derivada de dia_corte
    proxima_fecha_pago: date


class TarjetaEliminadaOut(EliminadoOut):
    planes_msi_eliminados: int
