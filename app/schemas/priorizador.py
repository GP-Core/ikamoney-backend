"""Esquemas de GET /priorizador: deudas y tarjetas ordenadas por costo real (T43, Fórmula 9
de T25).

Es la estructura que consumen la pantalla del ranking (T44) y la vista del plan de pagos
(T46). La sección `plan` la calcula T45 (Fórmula 10). Si cambia, avisar a los dos antes.
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


# ------------------------------------------------------------ plan de pagos (T45)
class AvisoPlanOut(BaseModel):
    codigo: Literal["EXCEDENTE_NO_SOSTENIBLE", "SIN_DINERO_EXTRA", "BASE_NO_SE_LIQUIDA",
                    "PLAN_NO_SE_LIQUIDA", "DEUDA_SIN_PAGO_MENSUAL"]
    mensaje: str


class DeudaPlanOut(BaseModel):
    """Cómo termina cada deuda con el plan y con el escenario base."""
    clave: str
    nombre: str
    posicion: int                        # la del ranking (T43)
    meses_plan: Optional[int]            # None si no se liquida en el horizonte
    liquidacion_plan: Optional[str]      # AAAA-MM del mes en que queda en cero
    intereses_plan: Optional[Dinero]     # None si con el plan no se liquida
    meses_base: Optional[int]            # pagando solo el mínimo
    liquidacion_base: Optional[str]
    intereses_base: Optional[Dinero]     # None si con el mínimo nunca se liquida


class PagoMesOut(BaseModel):
    clave: str
    pago: Dinero                         # mínimo + abono extra
    abono_extra: Dinero                  # lo que va por encima del mínimo
    saldo_final: Dinero


class MesPlanOut(BaseModel):
    mes: int                             # 1 = mes en curso
    periodo: str                         # AAAA-MM
    pagos: list[PagoMesOut]              # solo las deudas que todavía tienen saldo
    total_pagado: Dinero
    intereses: Dinero
    saldo_total: Dinero                  # lo que se sigue debiendo al terminar el mes


class TotalPlanOut(BaseModel):
    meses_plan: Optional[int]
    liquidacion_plan: Optional[str]
    intereses_plan: Optional[Dinero]     # None si el plan no liquida todo
    meses_base: Optional[int]
    liquidacion_base: Optional[str]
    intereses_base: Optional[Dinero]
    ahorro: Optional[Dinero]             # intereses_base − intereses_plan
    meses_menos: Optional[int]           # meses_base − meses_plan


class PlanOut(BaseModel):
    extra_mensual: Dinero                # el que pidió el usuario (parámetro extra_mensual)
    extra_sugerido: Dinero               # lo que le sobra en su peor mes (Fórmula 3), en cientos
    presupuesto_mensual: Dinero          # mínimos del mes 1 + extra; fijo todos los meses
    escenario_base: Literal["solo_minimo"]
    escenario_base_texto: str            # contra qué se compara el ahorro (mostrarlo en pantalla)
    deudas: list[DeudaPlanOut]           # en el orden del ranking
    total: TotalPlanOut
    calendario: list[MesPlanOut]         # mes a mes, hasta liquidar (máximo 120 meses)
    calendario_completo: bool            # False si el plan dura más de 120 meses
    mensaje: str
    avisos: list[AvisoPlanOut]
    supuestos: list[str]                 # por qué es una estimación


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
    plan: Optional[PlanOut]              # T45; None si no hay deudas con intereses