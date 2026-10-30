"""Lectura y validación de las reglas del score (app/core/reglas_score.json).

Las ponderaciones y los puntos de referencia viven en ese archivo, no en el código. Aquí solo
se leen y se validan: si los pesos no suman 100 o falta un factor, la aplicación no arranca
con un score equivocado, sino con un error claro.
"""
import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Optional

RUTA_REGLAS = Path(__file__).resolve().parents[1] / "core" / "reglas_score.json"

# Los cinco factores de T25. La fórmula de cada uno está en el código (score_formulas.py);
# lo que se configura es su peso y sus puntos de referencia.
FACTORES = ("relacion_deuda_ingreso", "utilizacion_credito", "flujo_libre", "carga_msi",
            "comportamiento_pago")
COMPORTAMIENTOS = ("pago_total", "mas_del_minimo", "solo_minimo", "con_atraso")
CIEN = Decimal("100")


class ReglasInvalidas(ValueError):
    """El archivo de reglas no cumple lo que pide T25 (pesos que no suman 100, etc.)."""


@dataclass(frozen=True)
class ReglaFactor:
    clave: str
    nombre: str
    formula: str
    peso: Decimal                                     # en porcentaje: 30 = 30 %
    justificacion_peso: str
    fuente_puntos: str
    puntos_referencia: tuple[tuple[Decimal, Decimal], ...] = ()
    subpuntajes_categoria: Optional[dict[str, Decimal]] = None
    omitible: bool = False


@dataclass(frozen=True)
class ReglasScore:
    version_modelo: str
    factores: dict[str, ReglaFactor]
    comportamiento_por_defecto: str
    tope_riesgo_inmediato: Decimal

    @property
    def suma_pesos(self) -> Decimal:
        return sum((f.peso for f in self.factores.values()), Decimal("0"))


def _error(mensaje: str) -> ReglasInvalidas:
    return ReglasInvalidas(f"Reglas del score inválidas: {mensaje}")


def _validar_puntos(clave: str, crudos) -> tuple[tuple[Decimal, Decimal], ...]:
    if not isinstance(crudos, list) or len(crudos) < 2:
        raise _error(f"'{clave}' necesita al menos 2 puntos de referencia.")
    puntos = tuple((Decimal(str(x)), Decimal(str(y))) for x, y in crudos)
    xs = [x for x, _ in puntos]
    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise _error(f"los puntos de '{clave}' deben ir de menor a mayor valor.")
    if any(not 0 <= y <= 100 for _, y in puntos):
        raise _error(f"los subpuntajes de '{clave}' deben estar entre 0 y 100.")
    return puntos


def construir(datos: dict) -> ReglasScore:
    """Convierte el JSON en reglas y valida todo lo que T25 exige."""
    factores: dict[str, ReglaFactor] = {}
    for f in datos.get("factores", []):
        clave = f.get("clave")
        if clave not in FACTORES:
            raise _error(f"factor desconocido '{clave}'.")
        if clave in factores:
            raise _error(f"el factor '{clave}' está repetido.")
        peso = Decimal(str(f.get("peso", "")))
        if peso < 0:
            raise _error(f"el peso de '{clave}' no puede ser negativo.")
        if not f.get("justificacion_peso"):
            raise _error(f"'{clave}' debe explicar por qué pesa lo que pesa (justificacion_peso).")
        categorias = None
        puntos: tuple = ()
        if clave == "comportamiento_pago":
            crudas = f.get("subpuntajes_categoria") or {}
            if set(crudas) != set(COMPORTAMIENTOS):
                raise _error(f"'comportamiento_pago' debe definir {', '.join(COMPORTAMIENTOS)}.")
            categorias = {k: Decimal(str(v)) for k, v in crudas.items()}
            if any(not 0 <= v <= 100 for v in categorias.values()):
                raise _error("los subpuntajes de 'comportamiento_pago' deben estar entre 0 y 100.")
        else:
            puntos = _validar_puntos(clave, f.get("puntos_referencia"))
        factores[clave] = ReglaFactor(
            clave=clave, nombre=f.get("nombre", clave), formula=f.get("formula", ""), peso=peso,
            justificacion_peso=f["justificacion_peso"], fuente_puntos=f.get("fuente_puntos", ""),
            puntos_referencia=puntos, subpuntajes_categoria=categorias,
            omitible=bool(f.get("omitible", False)))

    faltan = [c for c in FACTORES if c not in factores]
    if faltan:
        raise _error(f"faltan los factores {', '.join(faltan)}.")
    reglas = ReglasScore(
        version_modelo=str(datos.get("version_modelo") or ""),
        factores={c: factores[c] for c in FACTORES},          # siempre en el orden de T25
        comportamiento_por_defecto=datos.get("comportamiento_por_defecto", "solo_minimo"),
        tope_riesgo_inmediato=Decimal(str(datos.get("tope_riesgo_inmediato", 59))))
    if not reglas.version_modelo:
        raise _error("falta version_modelo.")
    if reglas.suma_pesos != CIEN:
        raise _error(f"los pesos suman {reglas.suma_pesos} y deben sumar 100.")
    if reglas.comportamiento_por_defecto not in COMPORTAMIENTOS:
        raise _error("comportamiento_por_defecto no es una categoría válida.")
    if not 0 <= reglas.tope_riesgo_inmediato <= 100:
        raise _error("tope_riesgo_inmediato debe estar entre 0 y 100.")
    return reglas


def leer(ruta: Path = RUTA_REGLAS) -> ReglasScore:
    with open(ruta, encoding="utf-8") as archivo:
        return construir(json.load(archivo))


@lru_cache
def reglas_vigentes() -> ReglasScore:
    """Reglas del archivo de configuración (se leen una vez por proceso)."""
    return leer()