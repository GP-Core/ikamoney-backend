"""Esquemas de /proyeccion: balance del mes y proyección de los meses siguientes (T33, T25 F1–F3)."""
from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.base import Dinero

EstadoProyeccion = Literal["completo", "sin_ingresos", "sin_datos"]
BaseGastosVariables = Literal["promedio_3_meses", "registrado", "sin_registros"]


class AvisoOut(BaseModel):
    codigo: str
    mensaje: str


class TarjetaMesOut(BaseModel):
    tarjeta_id: int
    nombre: str
    saldo_inicio: Dinero
    interes: Dinero                     # con IVA (Fórmula 5)
    pago: Dinero                        # pago mínimo o el planeado (Fórmula 6)
    saldo_fin: Dinero                   # Fórmula 2


class MesOut(BaseModel):
    mes: int                            # 1 = mes en curso
    periodo: str                        # AAAA-MM
    ingresos: Dinero
    gastos_fijos: Dinero
    gastos_variables: Dinero
    pagos_tarjetas: Dinero
    mensualidades_msi: Dinero
    otras_cuotas: Dinero
    compromisos: Dinero                 # pagos de tarjetas + MSI + otras cuotas
    flujo: Dinero                       # Fórmula 3: lo que queda en el mes
    acumulado: Dinero                   # Fórmula 3: ahorro inicial + flujos
    saldo_tarjetas: Dinero              # deuda en tarjetas al cerrar el mes (sin MSI)
    msi_activos: int
    tarjetas: list[TarjetaMesOut]


class ResumenOut(BaseModel):
    flujo_minimo: Dinero
    mes_flujo_minimo: int
    acumulado_minimo: Dinero
    meses_en_negativo: int              # meses con acumulado negativo
    saldo_tarjetas_final: Dinero


class SupuestosOut(BaseModel):
    ahorro_inicial: Dinero
    gastos_variables_estimados: Dinero
    base_gastos_variables: BaseGastosVariables
    pago_tarjetas: Literal["minimo"]    # todavía no se captura un pago planeado por tarjeta
    nota: str


class ProyeccionOut(BaseModel):
    estado: EstadoProyeccion
    mes_inicio: str                     # AAAA-MM del mes 1
    meses: int
    avisos: list[AvisoOut]
    supuestos: SupuestosOut
    balance_mes: Optional[MesOut]       # el mes 1; None si el usuario no tiene datos
    proyeccion: list[MesOut]
    resumen: Optional[ResumenOut]