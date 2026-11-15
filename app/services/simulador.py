"""Impacto de cada escenario de compra en la proyección y en el score (T41, Fórmula 4 de T25).

Responde: "si compro esto así, ¿cómo queda mi dinero en los próximos meses y cómo queda mi
score?". No tiene fórmulas propias: la proyección es el motor de T33 (formulas.proyectar) y el
score es el de T35 (score.evaluar). Aquí solo se arma cada escenario y se aplican las reglas
fijas del veredicto (RN-15 y RN-16). El veredicto lo decide este motor, nunca la IA: la IA solo
redacta la explicación en otra llamada (RN-17, decisión de T17).

Solo lee: simular una compra no modifica ningún dato del usuario (RN-17, REQ-SC-07).
"""
from dataclasses import replace
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Usuario
from app.schemas.simulacion import (EscenarioOut, EscenarioPedido, IndicadoresOut,
                                    MesSimuladoOut, MotivoOut, ScoreActualOut,
                                    ScoreSimuladoOut, SimulacionOut, SimulacionPedido)
from app.services import fechas, formulas, proyeccion, score
from app.services.formulas import CERO, MsiEntrada
from app.services.score_formulas import NIVELES, ResultadoScore
from app.services.score_reglas import reglas_vigentes

MSI_MIN_MESES = 2                                   # T18: un MSI tiene al menos 2 mensualidades
TEXTO_VEREDICTO = {
    "recomendable": "Recomendable",
    "con_precaucion": "Recomendable con precaución",
    "no_recomendable": "No recomendable por ahora",
}
TEXTO_SIN_OPCION = "No se recomienda realizar esta compra por ahora"   # Fórmula 4, regla 3
# 0 = mejor nivel (saludable) … 3 = peor (crítico), según los cortes fijos de T17
_ORDEN_NIVEL = {clave: i for i, (_, clave, _) in enumerate(NIVELES)}
_TEXTO_NIVEL = {clave: texto for _, clave, texto in NIVELES}


def _c(valor: Decimal) -> Decimal:
    return fechas.a_centavos(valor)


def _dinero(valor: Decimal) -> str:
    signo = "-" if valor < 0 else ""
    return f"{signo}${abs(_c(valor)):,.2f}"


# ------------------------------------------------------- reglas fijas (puras)
def horizonte(escenarios: list[EscenarioPedido]) -> int:
    """12 meses, o más si un plazo MSI es mayor, para ver el plan completo (máximo 24)."""
    plazos = [e.meses for e in escenarios if e.tipo == "msi" and e.meses
              and MSI_MIN_MESES <= e.meses <= settings.max_mensualidades]
    return min(max([formulas.HORIZONTE_DEFECTO, *plazos]), formulas.HORIZONTE_MAX)


def veredicto(prioridad: str, meses_en_negativo: int, nivel_simulado: str,
              nivel_actual: str) -> tuple[str, str, str]:
    """(veredicto, regla, razón) con las reglas RN-15 y RN-16.

    RN-15: si en algún mes el dinero no alcanza (acumulado < 0, Fórmula 4), no es recomendable.
    RN-16: si sí alcanza, depende de la prioridad del producto:
      alta  → recomendable aunque el índice baje;
      media → recomendable si el índice no queda en En riesgo o Crítico;
      baja  → recomendable solo si el índice se mantiene en el mismo nivel.
    Si no se cumple la condición de su prioridad, es "con precaución".
    """
    if meses_en_negativo > 0:
        return ("no_recomendable", "RN-15",
                "En al menos un mes tu dinero no alcanzaría para cubrir tus gastos y pagos.")
    texto_nuevo = _TEXTO_NIVEL[nivel_simulado]
    if prioridad == "alta":
        return ("recomendable", "RN-16",
                "Es una necesidad y tu dinero alcanza todos los meses, aunque tu índice cambie.")
    if prioridad == "media":
        if nivel_simulado in ("en_riesgo", "critico"):
            return ("con_precaucion", "RN-16",
                    f"Tu dinero alcanza, pero tu índice quedaría en nivel {texto_nuevo}.")
        return ("recomendable", "RN-16",
                f"Tu dinero alcanza y tu índice queda en nivel {texto_nuevo}.")
    if _ORDEN_NIVEL[nivel_simulado] > _ORDEN_NIVEL[nivel_actual]:
        antes = _TEXTO_NIVEL[nivel_actual]
        return ("con_precaucion", "RN-16",
                f"Es un gusto y tu índice bajaría de {antes} a {texto_nuevo}.")
    return ("recomendable", "RN-16",
            f"Tu dinero alcanza y tu índice se mantiene en nivel {texto_nuevo}.")


def elegir_menor_impacto(candidatos: list[tuple[str, int, Decimal, int]]) -> Optional[str]:
    """Id del escenario de menor impacto. Cada candidato: (id, meses_en_negativo,
    acumulado_minimo, puntaje); solo entran los escenarios que aplican.

    Fórmula 4: de los que no tienen meses en negativo, el de mayor score del mes 1; si empatan,
    el de mayor acumulado mínimo. Si todos tienen meses en negativo (RN-15), el que menos meses
    deja en negativo y luego el de mayor acumulado mínimo. Si todo empata, el primero pedido.
    """
    if not candidatos:
        return None
    viables = [c for c in candidatos if c[1] == 0]
    if viables:
        return max(viables, key=lambda c: (c[3], c[2]))[0]
    return min(candidatos, key=lambda c: (c[1], -c[2], -c[3]))[0]


def _disponible(tarjeta, planes) -> Decimal:
    """Crédito libre de la tarjeta: límite − saldo − lo que falta de sus MSI (Fórmula 12)."""
    pendiente = sum((formulas.pendiente_msi(p.monto_mensualidad, p.num_mensualidades,
                                            p.mensualidades_pagadas)
                     for p in planes if p.tarjeta_id == tarjeta.id), CERO)
    return tarjeta.limite_credito - tarjeta.saldo_actual - pendiente


def _id(e: EscenarioPedido) -> str:
    return "contado" if e.tipo == "contado" else f"msi-{e.tarjeta_id}-{e.meses}"


def _motivo(e: EscenarioPedido, precio: Decimal, prep: proyeccion.Preparacion,
            vistos: set[str]) -> Optional[MotivoOut]:
    """Por qué un escenario no es viable (aplica = false), o None si sí se puede simular."""
    if _id(e) in vistos:
        return MotivoOut(codigo="ESCENARIO_REPETIDO",
                         mensaje="Esta forma de pago ya está en la comparación.")
    if e.tipo == "contado":
        return None
    if not MSI_MIN_MESES <= e.meses <= settings.max_mensualidades:
        return MotivoOut(codigo="PLAZO_NO_VALIDO",
                         mensaje=f"No existe un plazo de {e.meses} meses: los MSI van de "
                                 f"{MSI_MIN_MESES} a {settings.max_mensualidades} meses.")
    tarjeta = next((t for t in prep.tarjetas if t.id == e.tarjeta_id), None)
    if tarjeta is None:
        return MotivoOut(codigo="TARJETA_NO_DISPONIBLE",
                         mensaje="La tarjeta no existe o está inactiva.")
    disponible = _disponible(tarjeta, prep.planes)
    if disponible < precio:                                            # REQ-SC-03
        if disponible <= 0:
            mensaje = f"La tarjeta {tarjeta.nombre} no tiene crédito disponible."
        else:
            mensaje = (f"La tarjeta {tarjeta.nombre} solo tiene {_dinero(disponible)} de crédito "
                       f"disponible y la compra es de {_dinero(precio)}.")
        return MotivoOut(codigo="LIMITE_INSUFICIENTE", mensaje=mensaje)
    return None


# -------------------------------------------------------------- un escenario
def _calcular(e: EscenarioPedido, pedido: SimulacionPedido, prep: proyeccion.Preparacion,
              reglas, meses: int, actual: ResultadoScore) -> EscenarioOut:
    """Mete la compra al motor de T33, recalcula el score con el de T35 y aplica RN-15/RN-16."""
    precio = pedido.precio
    if e.tipo == "contado":                       # CompraContado_1 = M; no toca la utilización
        entrada = replace(prep.entrada, compras_contado=[precio])
        mensualidad, extra_linea = precio, CERO
    else:                                         # plan nuevo: M ÷ n en los meses 1 a n
        plan = MsiEntrada(id=0, descripcion=pedido.descripcion, monto=precio, plazo=e.meses,
                          pagadas=0)
        entrada = replace(prep.entrada, planes_msi=[*prep.entrada.planes_msi, plan])
        mensualidad, extra_linea = formulas.mensualidad_msi(precio, e.meses), precio

    resultado = formulas.proyectar(entrada, meses)                     # motor de T33
    _, sim, _, _ = score.evaluar(prep, reglas, entrada, extra_linea)   # motor de T35

    balance = []
    for m in resultado.meses:
        if e.tipo == "contado":
            compra = m.compra_contado
        else:
            compra = mensualidad if formulas.msi_activo_en_mes(e.meses, 0, m.mes) else CERO
        anio, mes = prep.periodos[m.mes - 1]
        balance.append(MesSimuladoOut(
            mes=m.mes, periodo=f"{anio:04d}-{mes:02d}", ingresos=_c(m.ingresos),
            gastos=_c(m.gastos_fijos + m.gastos_variables), compromisos=_c(m.compromisos),
            compra=_c(compra), flujo=_c(m.flujo), acumulado=_c(m.acumulado)))

    negativos = [m.mes for m in resultado.meses if m.acumulado < 0]
    peor = min(resultado.meses, key=lambda m: (m.flujo, m.mes))
    indicadores = IndicadoresOut(
        flujo_minimo=_c(resultado.flujo_minimo), mes_flujo_minimo=peor.mes,
        acumulado_minimo=_c(resultado.acumulado_minimo),
        meses_en_negativo=len(negativos), primer_mes_negativo=negativos[0] if negativos else None)

    clave, regla, razon = veredicto(pedido.prioridad, len(negativos), sim.nivel, actual.nivel)
    if negativos:
        anio, mes = prep.periodos[negativos[0] - 1]
        acumulado = resultado.meses[negativos[0] - 1].acumulado
        razon = (f"En {anio:04d}-{mes:02d} tu dinero disponible quedaría en {_dinero(acumulado)}: "
                 "no alcanzaría para cubrir tus gastos y pagos.")
    tarjeta = next((t for t in prep.tarjetas if t.id == e.tarjeta_id), None)
    return EscenarioOut(
        id=_id(e), tipo=e.tipo, tarjeta_id=e.tarjeta_id,
        tarjeta_nombre=tarjeta.nombre if tarjeta else None, meses=e.meses, aplica=True,
        motivo=None, mensualidad=_c(mensualidad), balance=balance, indicadores=indicadores,
        score=ScoreSimuladoOut(puntaje=sim.puntaje, puntaje_bruto=float(_c(sim.puntaje_bruto)),
                               nivel=sim.nivel, nivel_texto=sim.nivel_texto,
                               tope_aplicado=sim.tope_aplicado, motivo_tope=sim.motivo_tope,
                               cambio=sim.puntaje - actual.puntaje),
        veredicto=clave, veredicto_texto=TEXTO_VEREDICTO[clave], regla=regla, razon=razon,
        menor_impacto=False)


def _no_aplica(e: EscenarioPedido, motivo: MotivoOut, prep: proyeccion.Preparacion) -> EscenarioOut:
    tarjeta = next((t for t in prep.tarjetas if t.id == e.tarjeta_id), None)
    return EscenarioOut(
        id=_id(e), tipo=e.tipo, tarjeta_id=e.tarjeta_id,
        tarjeta_nombre=tarjeta.nombre if tarjeta else None, meses=e.meses, aplica=False,
        motivo=motivo, mensualidad=None, balance=[], indicadores=None, score=None,
        veredicto=None, veredicto_texto=None, regla=None, razon=None, menor_impacto=False)


# ------------------------------------------------------------------ simular
def simular(db: Session, usuario: Usuario, pedido: SimulacionPedido) -> SimulacionOut:
    """Calcula todos los escenarios pedidos y señala el de menor impacto (T41).

    Lee los datos del usuario una sola vez (proyeccion.preparar) y reutiliza esa preparación en
    cada escenario, por eso responde en milisegundos aunque se comparen 6 formas de pago.
    """
    reglas = reglas_vigentes()
    meses = horizonte(pedido.escenarios)
    prep = proyeccion.preparar(db, usuario, meses, pedido.ahorro_inicial)
    periodo, actual, faltantes, supuestos = score.evaluar(prep, reglas)    # score sin la compra

    base = dict(periodo=periodo, descripcion=pedido.descripcion, precio=pedido.precio,
                prioridad=pedido.prioridad, meses=meses, version_modelo=reglas.version_modelo)
    if actual is None:                         # sin ingresos no se simula (REQ-SC-10, CE-03)
        return SimulacionOut(estado="datos_faltantes", score_actual=None, escenarios=[],
                             menor_impacto=None, veredicto=None, veredicto_texto=None,
                             faltantes=faltantes, supuestos=[], **base)

    escenarios: list[EscenarioOut] = []
    vistos: set[str] = set()
    for e in pedido.escenarios:
        motivo = _motivo(e, pedido.precio, prep, vistos)
        vistos.add(_id(e))
        escenarios.append(_no_aplica(e, motivo, prep) if motivo
                          else _calcular(e, pedido, prep, reglas, meses, actual))

    aplican = [e for e in escenarios if e.aplica]
    elegido = elegir_menor_impacto([(e.id, e.indicadores.meses_en_negativo,
                                     e.indicadores.acumulado_minimo, e.score.puntaje)
                                    for e in aplican])
    general = texto_general = None
    for e in escenarios:
        if e.id == elegido and e.aplica:
            e.menor_impacto = True
            general = e.veredicto
            texto_general = (TEXTO_SIN_OPCION if general == "no_recomendable"
                             else TEXTO_VEREDICTO[general])
            break

    supuestos = [*supuestos, f"Ahorro disponible hoy: {_dinero(pedido.ahorro_inicial)}."]
    if any(e.tipo == "contado" for e in aplican):
        supuestos.append("De contado se paga completo este mes, con efectivo o débito.")
    if any(e.tipo == "msi" for e in aplican):
        supuestos.append("A MSI la mensualidad es el precio entre los meses, y el total ocupa el "
                         "límite de la tarjeta desde el primer mes.")
    if any(e.tipo == "msi" and e.meses > meses for e in aplican):
        supuestos.append(f"La proyección muestra {meses} meses; los plazos más largos siguen "
                         "cobrando después.")

    return SimulacionOut(
        estado="calculado" if aplican else "sin_escenarios_validos",
        score_actual=ScoreActualOut(puntaje=actual.puntaje, nivel=actual.nivel,
                                    nivel_texto=actual.nivel_texto),
        escenarios=escenarios, menor_impacto=elegido, veredicto=general,
        veredicto_texto=texto_general, faltantes=faltantes, supuestos=supuestos, **base)