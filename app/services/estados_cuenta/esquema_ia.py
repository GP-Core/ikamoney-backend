"""Formato que debe devolver la IA (esquema de la PoC de T08, sin cambios).

Todas las llaves son obligatorias; si el documento no trae un dato, va null. Las descripciones de
los campos también le explican a la IA qué poner en cada uno. No es la respuesta de la API: esa
está en app/schemas/estado_cuenta.py y se arma en conversion.py.
"""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    # Una llave que no está en el esquema (por ejemplo "titular") hace que la respuesta sea inválida.
    model_config = ConfigDict(extra="forbid")


class Periodo(_Base):
    inicio: Optional[date]
    fin: Optional[date]


class Pagos(_Base):
    total_a_pagar_periodo: Optional[float] = Field(
        description="Saldo total que el banco reporta al corte ('saldo deudor total' o 'saldo al corte')."
    )
    pago_para_no_generar_intereses: Optional[float]
    pago_minimo: Optional[float]
    pago_minimo_mas_msi: Optional[float] = Field(
        description="Pago mínimo más mensualidades a meses, solo si el documento lo muestra."
    )


class Credito(_Base):
    limite_credito: Optional[float]
    credito_disponible: Optional[float]


class Tasas(_Base):
    cat: Optional[float] = Field(
        description="CAT tal como lo reporta el banco, en porcentaje (suele aparecer como 'X% sin IVA')."
    )
    tasa_interes_anual: Optional[float] = Field(description="Tasa de interés anual ordinaria, en porcentaje.")
    tasa_interes_mensual: Optional[float]


class ResumenPeriodo(_Base):
    saldo_anterior: Optional[float]
    cargos: Optional[float] = Field(
        description="Cargos regulares del periodo, sin compras a meses ('Cargos regulares (no a meses)' o 'Compras')."
    )
    abonos: Optional[float] = Field(description="Total de pagos y abonos del periodo, en negativo.")
    intereses: Optional[float]
    comisiones: Optional[float]
    iva: Optional[float]
    saldo_pendiente_msi: Optional[float] = Field(
        description="Lo que falta por pagar de todas las compras a meses (suma de sus saldos pendientes), "
                    "solo si el documento lo muestra; no es la suma de las mensualidades de este periodo."
    )


class Meses(_Base):
    mensualidad_actual: Optional[int]
    meses_totales: Optional[int]
    monto_original: Optional[float] = Field(description="Monto total de la compra a meses.")
    saldo_pendiente: Optional[float] = Field(description="Saldo pendiente de esta compra, si aparece.")


class MovimientoIA(_Base):
    fecha: date
    concepto: str
    monto: float = Field(
        description="Cargos positivos; pagos y abonos negativos. En compras a meses: la mensualidad de este periodo."
    )
    tipo: Literal["compra", "pago", "devolucion", "comision", "interes", "impuesto", "otro"]
    modalidad: Optional[Literal["contado", "msi", "meses_con_intereses"]]
    meses: Optional[Meses]


class EstadoCuentaIA(_Base):
    banco: Optional[str]
    producto: Optional[str] = Field(description="Nombre comercial del producto si el documento lo trae; si no, null.")
    moneda: Optional[str]
    periodo: Optional[Periodo]
    fecha_corte: Optional[date]
    fecha_limite_pago: Optional[date]
    pagos: Pagos
    credito: Credito
    tasas: Tasas
    resumen_periodo: ResumenPeriodo
    movimientos: list[MovimientoIA]


def _resolver_refs(nodo, defs):
    """Inserta las definiciones en lugar de cada $ref y quita los 'title' (esquema plano, menos tokens)."""
    if isinstance(nodo, dict):
        if "$ref" in nodo:
            resuelto = dict(defs[nodo["$ref"].split("/")[-1]])
            resuelto.update({k: v for k, v in nodo.items() if k != "$ref"})
            return _resolver_refs(resuelto, defs)
        return {k: _resolver_refs(v, defs) for k, v in nodo.items() if k not in ("$defs", "title")}
    if isinstance(nodo, list):
        return [_resolver_refs(x, defs) for x in nodo]
    return nodo


def esquema_json() -> dict:
    """Esquema JSON que se le pasa a la IA y que se inserta en el prompt."""
    esquema = EstadoCuentaIA.model_json_schema()
    return _resolver_refs(esquema, esquema.get("$defs", {}))
