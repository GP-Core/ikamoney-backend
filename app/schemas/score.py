"""Esquemas de /score y /score/historial (T35, Índice de Salud Financiera de T25).

Esta es la estructura que consumen el dashboard (T34), el detalle del score (T37) y las pruebas
(T38). Si cambia, avisar a esos tres antes.
"""
from datetime import datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel

Nivel = Literal["saludable", "en_revision", "en_riesgo", "critico"]
ClaveFactor = Literal["relacion_deuda_ingreso", "utilizacion_credito", "flujo_libre",
                      "carga_msi", "comportamiento_pago"]


class FactorOut(BaseModel):
    clave: ClaveFactor
    nombre: str
    formula: str                          # la fórmula de T25 en palabras
    disponible: bool                      # False: se omitió (sin tarjetas) y su peso se repartió
    peso: float                           # peso configurado, en % (los cinco suman 100)
    peso_efectivo: float                  # peso usado tras repartir los omitidos, en %
    valor: Optional[float]                # en % (20.81 = 20.81 %); None en comportamiento u omitido
    categoria: Optional[str]              # solo comportamiento_pago
    subpuntaje: Optional[float]           # 0 a 100
    aporte: float                         # puntos que suma al score
    puntos_perdidos: float                # puntos que deja de sumar (regla 4 de T25)
    explicacion: str                      # por qué obtuvo ese subpuntaje
    como_mejorar: str
    justificacion_peso: str               # por qué pesa lo que pesa (T25)
    datos: dict[str, Union[float, str]]   # números con los que se calculó


class FaltanteOut(BaseModel):
    dato: Literal["ingresos", "gastos"]
    obligatorio: bool                     # True: sin este dato no hay score
    mensaje: str


class ScoreOut(BaseModel):
    estado: Literal["calculado", "datos_faltantes"]
    puntaje: Optional[int]                # 0 a 100; None si faltan datos
    puntaje_bruto: Optional[float]        # promedio ponderado antes del tope y del redondeo
    nivel: Optional[Nivel]
    nivel_texto: Optional[str]
    tope_aplicado: bool
    motivo_tope: Optional[Literal["flujo_negativo", "pago_con_atraso"]]
    periodo: str                          # AAAA-MM del mes evaluado
    version_modelo: str
    factores: list[FactorOut]             # siempre los cinco, en el orden de T25 (vacío si faltan datos)
    orden_mejora: list[ClaveFactor]       # de la que más puntos pierde a la que menos
    faltantes: list[FaltanteOut]
    supuestos: list[str]


class PuntoHistorialOut(BaseModel):
    periodo: str                          # AAAA-MM
    puntaje: int
    nivel: Nivel
    nivel_texto: str
    calculado_en: datetime                # último cálculo de ese mes
    version_modelo: str


class HistorialOut(BaseModel):
    meses: int
    puntos: list[PuntoHistorialOut]       # del mes más antiguo al más reciente; solo meses con score