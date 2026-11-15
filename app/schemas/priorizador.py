"""Esquemas de GET /priorizador: deudas y tarjetas ordenadas por costo real (T43, Fórmula 9
de T25).

Es la estructura que consume la pantalla del ranking (T44) y el plan de pagos (T45).
Si cambia, avisar a los dos antes.
"""
from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.base import Dinero

TipoDeuda = Literal["tarjeta", "deuda"]
Criterio = Literal["tasa", "utilizacion", "saldo", "empate"]


class AvisoOut(BaseModel):
    codigo: Literal["LIMITE_CERO", "SOBRE_LIMITE", "SIN_PAGO_MENSUAL", "PAGO_NO_CUBRE_INTERES"]
    mensaje: str


class ComparacionOut(BaseModel):
    """Contra la deuda de la posición anterior: por qué esta va después."""
    contra: str                          # clave de la deuda anterior ("tarjeta-1")
    contra_nombre: str
    criterio: Criterio                   # qué decidió el orden (Fórmula 9)
    ahorro_por_mil_menos: Dinero         # cuánto menos ahorra al mes cada $1,000 abonados aquí


class PosicionOut(BaseModel):
    posicion: int                        # 1 = la que conviene liquidar primero
    clave: str                           # "tarjeta-<id>" o "deuda-<id>"
    tipo: TipoDeuda
    id: int
    nombre: str
    saldo: Dinero
    tasa_anual: float                    # en %, como la captura el usuario
    tasa_mensual: float                  # r' en % (tarjetas con IVA, Fórmula 5)
    costo_anual_compuesto: float         # (1 + r')^12 − 1, en % (Fórmula 5)
    interes_mes: Dinero                  # intereses que genera este mes (Fórmula 5)
    utilizacion: Optional[float]         # (saldo + MSI pendiente) ÷ límite, en %; None en deudas
    pago_minimo: Optional[Dinero]        # tarjetas: Fórmula 6; deudas: su pago mensual
    ahorro_por_mil: Dinero               # intereses que se ahorran al mes por cada $1,000 abonados
    accion: Literal["abonar_extra", "pagar_minimo"]   # RN-20
    razon: str                           # por qué va en esta posición, en dinero
    comparacion: Optional[ComparacionOut]             # None en la posición 1
    avisos: list[AvisoOut]


class SinRankingOut(BaseModel):
    """Deudas que no entran al orden, con el motivo."""
    clave: str
    tipo: Literal["tarjeta", "deuda", "msi"]
    id: int
    nombre: str
    saldo: Dinero                        # MSI: lo que falta por pagar
    pago_mensual: Optional[Dinero]
    motivo: Literal["MSI", "SIN_INTERESES", "SIN_SALDO", "SIN_TASA"]
    mensaje: str


class BolaDeNieveOut(BaseModel):
    """Contraste con el consejo popular de pagar primero la deuda más chica."""
    coincide: bool
    mas_chica: str                       # clave de la deuda con menor saldo del ranking
    mas_chica_nombre: str
    diferencia_por_mil: Dinero           # intereses de más al mes por cada $1,000 a la chica
    mensaje: str


class PriorizadorOut(BaseModel):
    estado: Literal["calculado", "sin_deudas"]
    periodo: str                         # AAAA-MM
    ranking: list[PosicionOut]           # de la más cara a la más barata
    sin_ranking: list[SinRankingOut]
    resumen: str                         # qué hacer este mes (RN-20)
    intereses_mes_total: Dinero          # de las deudas del ranking
    pagos_minimos_total: Dinero          # pagos mínimos y cuotas del ranking (RN-20)
    msi_mes_total: Dinero                # mensualidades MSI del mes: pagos fijos (RN-19)
    bola_de_nieve: Optional[BolaDeNieveOut]
    supuestos: list[str]