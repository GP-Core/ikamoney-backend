"""Índice de Salud Financiera de T25 (Fórmulas 11 a 14, subpuntajes, pesos, niveles y reglas).

Reglas de T25 que se aplican:
1. Cada factor se convierte a un subpuntaje de 0 a 100 interpolando entre puntos de referencia.
2. Score = Σ peso × subpuntaje ÷ Σ peso de los factores disponibles (regla 3: sin tarjetas,
   la utilización se omite y su peso se reparte en proporción).
3. Tope por riesgo inmediato: con flujo negativo o pago con atraso, el score no pasa de 59.
4. Redondeo al entero más cercano; .5 sube (77.5 → 78).
5. Puntos perdidos por factor = peso × (100 − subpuntaje): el que más pierde se mejora primero.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app.services.score_reglas import ReglaFactor, ReglasScore

CERO = Decimal("0")
CIEN = Decimal("100")

# Niveles fijos de T17 (límite inferior, clave, texto). No son configurables.
NIVELES = (
    (Decimal("80"), "saludable", "Saludable"),
    (Decimal("60"), "en_revision", "En revisión"),
    (Decimal("40"), "en_riesgo", "En riesgo"),
    (Decimal("0"), "critico", "Crítico"),
)

COMPORTAMIENTO_TEXTO = {
    "pago_total": "pagas el total",
    "mas_del_minimo": "pagas más del mínimo",
    "solo_minimo": "pagas solo el mínimo",
    "con_atraso": "pagaste con atraso",
}

COMO_MEJORAR = {
    "relacion_deuda_ingreso": "Baja tus pagos mensuales de deudas o aumenta tu ingreso; lo ideal es "
                              "que no pasen del 30 % de lo que ganas.",
    "utilizacion_credito": "Baja el saldo de tus tarjetas por debajo del 30 % de su límite.",
    "flujo_libre": "Recorta gastos variables o compromisos para que te quede al menos el 20 % de "
                   "tu ingreso cada mes.",
    "carga_msi": "Evita nuevas compras a meses sin intereses hasta que terminen las actuales; lo "
                 "ideal es que las mensualidades no pasen del 10 % de tu ingreso.",
    "comportamiento_pago": "Paga más del mínimo, y si puedes el total, antes de la fecha límite.",
}


# ------------------------------------------------------------------- entradas
@dataclass(frozen=True)
class EntradaScore:
    """Situación del usuario en el mes en curso (sale del motor de balance de T33)."""
    ingreso: Decimal                 # ingreso neto del mes
    compromisos: Decimal             # pagos mínimos + mensualidades MSI + otras cuotas
    mensualidades_msi: Decimal       # mensualidades MSI del mes
    flujo: Decimal                   # Fórmula 3, mes 1
    saldo_tarjetas: Decimal          # Σ saldo revolvente de tarjetas activas
    pendiente_msi: Decimal           # Σ pendiente de MSI de esas tarjetas
    limite_total: Decimal            # Σ límite de tarjetas activas
    comportamiento_pago: str         # pago_total | mas_del_minimo | solo_minimo | con_atraso


# -------------------------------------------------------------------- salidas
@dataclass(frozen=True)
class FactorCalculado:
    clave: str
    nombre: str
    formula: str
    peso: Decimal                    # peso configurado (%)
    peso_efectivo: Decimal           # peso tras repartir los factores omitidos (%)
    disponible: bool
    valor: Optional[Decimal]         # en porcentaje (20.81 = 20.81 %); None si no aplica
    categoria: Optional[str]         # solo comportamiento de pago
    subpuntaje: Optional[Decimal]    # 0 a 100
    aporte: Decimal                  # puntos que suma al score
    puntos_perdidos: Decimal         # puntos que deja de sumar
    explicacion: str
    como_mejorar: str
    justificacion_peso: str
    datos: dict


@dataclass(frozen=True)
class ResultadoScore:
    puntaje: int
    puntaje_bruto: Decimal           # promedio ponderado antes del tope y del redondeo
    nivel: str
    nivel_texto: str
    tope_aplicado: bool
    motivo_tope: Optional[str]       # flujo_negativo | pago_con_atraso
    factores: list[FactorCalculado]
    orden_mejora: list[str]          # claves, de la que más puntos pierde a la que menos
    version_modelo: str


# ------------------------------------------------------------ Fórmulas 11 a 14
def porcentaje(numerador: Decimal, denominador: Decimal) -> Decimal:
    return numerador / denominador * CIEN


def interpolar(valor: Decimal, puntos: tuple[tuple[Decimal, Decimal], ...]) -> Decimal:
    """Subpuntaje por interpolación lineal entre puntos de referencia. Fuera del rango se usa
    el extremo (CE-10: utilización mayor a 100 % vale 0)."""
    if valor <= puntos[0][0]:
        return puntos[0][1]
    for (x0, y0), (x1, y1) in zip(puntos, puntos[1:]):
        if valor <= x1:
            return y0 + (valor - x0) * (y1 - y0) / (x1 - x0)
    return puntos[-1][1]


def nivel_de(puntaje: Decimal | int) -> tuple[str, str]:
    """Nivel según los cortes fijos de T17."""
    for minimo, clave, texto in NIVELES:
        if Decimal(puntaje) >= minimo:
            return clave, texto
    return NIVELES[-1][1], NIVELES[-1][2]


def redondear(valor: Decimal) -> int:
    """Entero más cercano; .5 sube (CE-06)."""
    return int(valor.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _texto_pct(valor: Decimal) -> str:
    return f"{valor.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} %"


def _explicacion(clave: str, valor: Optional[Decimal], categoria: Optional[str],
                 subpuntaje: Optional[Decimal]) -> str:
    if valor is None and categoria is None:
        return "No tienes tarjetas de crédito registradas, así que este factor no se toma en cuenta."
    puntos = f"{subpuntaje.quantize(Decimal('1'), rounding=ROUND_HALF_UP)} de 100"
    if clave == "relacion_deuda_ingreso":
        return (f"Destinas el {_texto_pct(valor)} de tu ingreso a pagar tarjetas, MSI y otras "
                f"deudas. Este factor obtiene {puntos}.")
    if clave == "utilizacion_credito":
        return (f"Usas el {_texto_pct(valor)} del límite de tus tarjetas, contando lo que falta de "
                f"tus MSI. Este factor obtiene {puntos}.")
    if clave == "flujo_libre":
        if valor < 0:
            return (f"Tus gastos y compromisos superan tu ingreso en {_texto_pct(-valor)}. "
                    f"Este factor obtiene {puntos}.")
        return (f"Después de gastos y compromisos te queda el {_texto_pct(valor)} de tu ingreso. "
                f"Este factor obtiene {puntos}.")
    if clave == "carga_msi":
        return (f"Tus mensualidades a meses sin intereses son el {_texto_pct(valor)} de tu "
                f"ingreso. Este factor obtiene {puntos}.")
    return f"En tu último periodo {COMPORTAMIENTO_TEXTO[categoria]}. Este factor obtiene {puntos}."


def calcular(entrada: EntradaScore, reglas: ReglasScore) -> ResultadoScore:
    """Índice de Salud Financiera con su desglose por factor."""
    if entrada.ingreso <= 0:
        raise ValueError("Sin ingreso no se calcula el score (CE-03).")
    if entrada.comportamiento_pago not in COMPORTAMIENTO_TEXTO:
        raise ValueError(f"Comportamiento de pago desconocido: {entrada.comportamiento_pago}")

    # Valor de cada factor (en porcentaje) o None si no hay datos para él
    valores: dict[str, Optional[Decimal]] = {
        "relacion_deuda_ingreso": porcentaje(entrada.compromisos, entrada.ingreso),
        "utilizacion_credito": (porcentaje(entrada.saldo_tarjetas + entrada.pendiente_msi,
                                           entrada.limite_total)
                                if entrada.limite_total > 0 else None),        # regla 3, CE-04
        "flujo_libre": porcentaje(entrada.flujo, entrada.ingreso),
        "carga_msi": porcentaje(entrada.mensualidades_msi, entrada.ingreso),
    }
    datos = {
        "relacion_deuda_ingreso": {"compromisos": entrada.compromisos, "ingreso": entrada.ingreso},
        "utilizacion_credito": {"saldo_tarjetas": entrada.saldo_tarjetas,
                                "pendiente_msi": entrada.pendiente_msi,
                                "limite_total": entrada.limite_total},
        "flujo_libre": {"flujo": entrada.flujo, "ingreso": entrada.ingreso},
        "carga_msi": {"mensualidades_msi": entrada.mensualidades_msi, "ingreso": entrada.ingreso},
        "comportamiento_pago": {"categoria": entrada.comportamiento_pago},
    }

    # Subpuntajes
    subpuntajes: dict[str, Optional[Decimal]] = {}
    for clave, regla in reglas.factores.items():
        if clave == "comportamiento_pago":
            subpuntajes[clave] = regla.subpuntajes_categoria[entrada.comportamiento_pago]
        elif valores[clave] is None:
            subpuntajes[clave] = None
        else:
            subpuntajes[clave] = interpolar(valores[clave], regla.puntos_referencia)

    # Promedio ponderado con los factores disponibles (regla 3)
    disponibles = [c for c, s in subpuntajes.items() if s is not None]
    suma_pesos = sum((reglas.factores[c].peso for c in disponibles), CERO)
    factores: list[FactorCalculado] = []
    # Σ peso × subpuntaje ÷ Σ peso, en ese orden para no arrastrar decimales periódicos
    bruto = sum((reglas.factores[c].peso * subpuntajes[c] for c in disponibles), CERO) / suma_pesos
    for clave, regla in reglas.factores.items():
        s = subpuntajes[clave]
        disponible = s is not None
        peso_ef = regla.peso / suma_pesos * CIEN if disponible else CERO
        aporte = peso_ef * s / CIEN if disponible else CERO
        perdidos = peso_ef * (CIEN - s) / CIEN if disponible else CERO
        categoria = entrada.comportamiento_pago if clave == "comportamiento_pago" else None
        factores.append(FactorCalculado(
            clave=clave, nombre=regla.nombre, formula=regla.formula, peso=regla.peso,
            peso_efectivo=peso_ef, disponible=disponible, valor=valores.get(clave),
            categoria=categoria, subpuntaje=s, aporte=aporte, puntos_perdidos=perdidos,
            explicacion=_explicacion(clave, valores.get(clave), categoria, s),
            como_mejorar=COMO_MEJORAR[clave], justificacion_peso=regla.justificacion_peso,
            datos=datos[clave]))

    # Tope por riesgo inmediato
    motivo = None
    if entrada.flujo < 0:
        motivo = "flujo_negativo"
    elif entrada.comportamiento_pago == "con_atraso":
        motivo = "pago_con_atraso"
    final = min(bruto, reglas.tope_riesgo_inmediato) if motivo else bruto
    tope_aplicado = motivo is not None and bruto > reglas.tope_riesgo_inmediato
    puntaje = redondear(final)
    nivel, nivel_texto = nivel_de(puntaje)

    orden = [f.clave for f in sorted((f for f in factores if f.puntos_perdidos > 0),
                                     key=lambda f: f.puntos_perdidos, reverse=True)]
    return ResultadoScore(puntaje=puntaje, puntaje_bruto=bruto, nivel=nivel,
                          nivel_texto=nivel_texto, tope_aplicado=tope_aplicado,
                          motivo_tope=motivo if tope_aplicado else None, factores=factores,
                          orden_mejora=orden, version_modelo=reglas.version_modelo)