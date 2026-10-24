"""Respuesta de POST /estados-cuenta/extraer (T17 §4, versión del 09/10/2026).

T17 define estas llaves en camelCase. Un dato que no viene en el PDF va como null: no se inventa,
no se pone 0 y no se omite la llave.
"""
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.schemas.base import Dia, Dinero


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TarjetaExtraidaOut(_Camel):
    banco: Optional[str]
    limite_credito: Optional[Dinero]
    saldo_actual: Optional[Dinero]
    tasa_anual: Optional[Dinero]        # en porcentaje: 45.5 = 45.5 %
    pago_minimo: Optional[Dinero]
    pago_no_intereses: Optional[Dinero]     # pago para no generar intereses (estado_cuenta, T18)
    dia_corte: Optional[Dia]            # día del mes, no fecha completa
    dia_limite_pago: Optional[Dia]


class MsiExtraidoOut(_Camel):
    descripcion: str
    monto_total: Optional[Dinero]
    meses: Optional[int]
    mensualidades_pagadas: Optional[int]


class MovimientoExtraidoOut(_Camel):
    fecha: date
    concepto: str
    monto: Dinero


class EstadoCuentaExtraidoOut(_Camel):
    tarjeta: TarjetaExtraidaOut
    msi: list[MsiExtraidoOut]
    movimientos: list[MovimientoExtraidoOut]
