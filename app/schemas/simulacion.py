"""Esquemas del simulador de compras: lo que recibe el endpoint (T40) y lo que devuelve el motor
que calcula el impacto de cada escenario (T41, Fórmula 4 de T25).

Es la interfaz acordada entre T40 y T41: el endpoint valida el cuerpo con SimulacionPedido y
llama a app.services.simulador.simular(db, usuario, pedido), que devuelve SimulacionOut.
Si cambia, avisar a T40 y a la pantalla del simulador antes.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.base import Dinero, Entrada
from app.schemas.score import FaltanteOut, Nivel

Prioridad = Literal["alta", "media", "baja"]            # RN-14
TipoEscenario = Literal["contado", "msi"]
Veredicto = Literal["recomendable", "con_precaucion", "no_recomendable"]
MAX_ESCENARIOS = 6


# ------------------------------------------------------------------- entrada
class EscenarioPedido(Entrada):
    """Una forma de pago a comparar.

    De contado: {"tipo": "contado"}. A MSI: {"tipo": "msi", "tarjeta_id": 1, "meses": 12}.
    Que la tarjeta sea del usuario, que tenga crédito y que el plazo exista lo revisa el motor:
    si no se cumple, el escenario regresa con aplica = false y su motivo (no es un error 422).
    """
    tipo: TipoEscenario
    tarjeta_id: Optional[int] = Field(default=None, ge=1)
    meses: Optional[int] = None

    @model_validator(mode="after")
    def _campos_del_tipo(self):
        if self.tipo == "msi" and (self.tarjeta_id is None or self.meses is None):
            raise ValueError("Una compra a MSI necesita tarjeta_id y meses.")
        if self.tipo == "contado" and (self.tarjeta_id is not None or self.meses is not None):
            raise ValueError("Una compra de contado no lleva tarjeta_id ni meses.")
        return self


class SimulacionPedido(Entrada):
    descripcion: str = Field(min_length=1, max_length=120)
    precio: Dinero = Field(gt=0)                         # REQ-SC-03
    prioridad: Prioridad                                 # REQ-SC-02
    ahorro_inicial: Dinero = Field(default=0, ge=0)      # Acumulado_0 de la Fórmula 3
    escenarios: list[EscenarioPedido] = Field(min_length=1, max_length=MAX_ESCENARIOS)


class SimulacionPeticion(SimulacionPedido):
    """Cuerpo de POST /simulador/calcular (T40). Igual que SimulacionPedido, pero `escenarios` es
    opcional: si no se manda (o llega vacío), el endpoint evalúa los escenarios por omisión
    (services/simulaciones.py). Al motor siempre le llega un SimulacionPedido completo."""
    escenarios: Optional[list[EscenarioPedido]] = None

    @field_validator("escenarios")
    @classmethod
    def _maximo(cls, valor):
        if valor is not None and len(valor) > MAX_ESCENARIOS:
            raise ValueError(f"Máximo {MAX_ESCENARIOS} escenarios.")
        return valor


# -------------------------------------------------------------------- salida
class MotivoOut(BaseModel):
    codigo: Literal["PLAZO_NO_VALIDO", "TARJETA_NO_DISPONIBLE", "LIMITE_INSUFICIENTE",
                    "ESCENARIO_REPETIDO"]
    mensaje: str


class MesSimuladoOut(BaseModel):
    mes: int                         # 1 = mes en curso
    periodo: str                     # AAAA-MM
    ingresos: Dinero
    gastos: Dinero                   # fijos + variables
    compromisos: Dinero              # pagos de tarjetas + MSI (incluida la compra) + otras cuotas
    compra: Dinero                   # lo que cuesta la compra simulada ese mes
    flujo: Dinero                    # Fórmula 3 con la compra incluida
    acumulado: Dinero                # balance disponible: ahorro inicial + flujos


class IndicadoresOut(BaseModel):
    flujo_minimo: Dinero
    mes_flujo_minimo: int
    acumulado_minimo: Dinero
    meses_en_negativo: int           # meses con acumulado < 0 (Fórmula 4)
    primer_mes_negativo: Optional[int]


class ScoreSimuladoOut(BaseModel):
    puntaje: int
    puntaje_bruto: float
    nivel: Nivel
    nivel_texto: str
    tope_aplicado: bool
    motivo_tope: Optional[str]
    cambio: int                      # puntaje simulado − puntaje actual


class EscenarioOut(BaseModel):
    id: str                          # "contado" o "msi-<tarjeta_id>-<meses>"
    tipo: TipoEscenario
    tarjeta_id: Optional[int]
    tarjeta_nombre: Optional[str]
    meses: Optional[int]
    aplica: bool
    motivo: Optional[MotivoOut]      # solo si aplica = false
    mensualidad: Optional[Dinero]    # contado: el precio completo este mes; MSI: precio ÷ meses
    balance: list[MesSimuladoOut]    # vacío si no aplica
    indicadores: Optional[IndicadoresOut]
    score: Optional[ScoreSimuladoOut]
    veredicto: Optional[Veredicto]
    veredicto_texto: Optional[str]
    regla: Optional[Literal["RN-15", "RN-16"]]
    razon: Optional[str]             # por qué, con reglas fijas (la IA solo redacta aparte)
    menor_impacto: bool


class ScoreActualOut(BaseModel):
    puntaje: int
    nivel: Nivel
    nivel_texto: str


class SimulacionOut(BaseModel):
    estado: Literal["calculado", "datos_faltantes", "sin_escenarios_validos"]
    periodo: str                     # AAAA-MM del mes 1
    descripcion: str
    precio: Dinero
    prioridad: Prioridad
    meses: int                       # horizonte de la proyección
    score_actual: Optional[ScoreActualOut]
    escenarios: list[EscenarioOut]
    menor_impacto: Optional[str]     # id del escenario de menor impacto
    veredicto: Optional[Veredicto]   # veredicto general (el del escenario de menor impacto)
    veredicto_texto: Optional[str]
    faltantes: list[FaltanteOut]
    supuestos: list[str]
    version_modelo: str