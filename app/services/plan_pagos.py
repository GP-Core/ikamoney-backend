"""Plan de pagos y ahorro estimado (T45, Fórmula 10 de T25).

Continúa el ranking del priorizador (T43): con el orden por costo real, dice cuánto abonar a
cada deuda cada mes, cuándo queda liquidada cada una y cuánto se ahorra en intereses contra un
escenario base explícito.

Fórmula 10:
    Presupuesto = Σ PagoMín_k,1 + extra_mensual        (fijo todos los meses)
    Cada mes se cubre primero el mínimo de todas las deudas (RN-20) y el resto se abona a la
    deuda con la posición más alta del ranking que siga viva. Si esa se liquida, lo que sobra
    pasa a la siguiente en el mismo mes.
    Ahorro = Intereses(solo mínimo) − Intereses(plan)

Escenario base: pagar solo el mínimo de cada deuda cada mes, sin abonos extra (lo que define la
Fórmula 10 y lo que usa la hoja T26). Es una estimación: supone que no hay compras nuevas, que las
tasas no cambian y que los pagos se hacen a tiempo.

No tiene fórmulas propias de interés: usa priorizador.interes_y_minimo (Fórmulas 5 y 6).
"""
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Optional

from app.schemas.priorizador import (AvisoPlanOut, DeudaPlanOut, MesPlanOut, PagoMesOut,
                                     PlanOut, TotalPlanOut)
from app.services import fechas
from app.services.formulas import CERO, UMBRAL_SALDO_CERO
from app.services.priorizador import Costo, interes_y_minimo

MESES_MAX = 600              # 50 años: si no se liquida en ese tiempo, se considera que nunca
CALENDARIO_MAX = 120         # meses que se devuelven mes a mes en la respuesta
CIEN = Decimal("100")
ESCENARIO_BASE_TEXTO = ("Pagar solo el mínimo de cada deuda cada mes, sin abonos extra. El ahorro "
                        "es la diferencia de intereses entre ese escenario y este plan.")
SUPUESTOS = [
    "Es una estimación: supone que no haces compras nuevas con tus tarjetas y que las tasas de "
    "interés no cambian.",
    "Supone que todos los pagos se hacen a tiempo, sin cargos por atraso ni comisiones.",
    "El presupuesto se mantiene fijo cada mes: los pagos mínimos de hoy más tu extra. Cuando un "
    "mínimo baja o una deuda se liquida, ese dinero se abona a la siguiente deuda del ranking.",
    "Los intereses se calculan con el saldo de cada mes; en las tarjetas incluyen 16 % de IVA.",
    "Las mensualidades de MSI se pagan aparte y no forman parte del plan (RN-19).",
]


# ------------------------------------------------------------- cálculo (puro)
@dataclass
class Simulacion:
    """Resultado de pagar una lista de deudas mes a mes."""
    meses: Optional[int]                                  # None si no se liquida todo
    intereses: list[Decimal]                              # por deuda, en el orden recibido
    fin: list[Optional[int]]                              # mes en que se liquidó cada deuda
    # (mes, [(índice de la deuda, pago, abono extra, saldo final)], intereses del mes)
    calendario: list[tuple[int, list[tuple[int, Decimal, Decimal, Decimal]], Decimal]] = \
        field(default_factory=list)


def presupuesto(orden: list[Costo], extra: Decimal) -> Decimal:
    """Σ PagoMín_k,1 + extra (Fórmula 10)."""
    return sum((k.pago_minimo for k in orden), CERO) + extra


def simular_plan(orden: list[Costo], extra: Decimal, meses_max: int = MESES_MAX,
                 guardar_calendario: bool = True) -> Simulacion:
    """Método avalancha con presupuesto fijo. Todas las deudas de `orden` deben tener pago."""
    saldos = [k.candidata.saldo for k in orden]
    intereses = [CERO] * len(orden)
    fin: list[Optional[int]] = [None] * len(orden)
    total = presupuesto(orden, extra)
    sim = Simulacion(meses=None, intereses=intereses, fin=fin)
    for mes in range(1, meses_max + 1):
        if all(s <= UMBRAL_SALDO_CERO for s in saldos):
            break
        calculo = [interes_y_minimo(k.candidata, s) for k, s in zip(orden, saldos)]
        pagos = [m for _, m in calculo]
        disponible = max(total - sum(pagos, CERO), CERO)                # RN-20: mínimos primero
        for i, (k, s) in enumerate(zip(orden, saldos)):                 # el resto, en orden
            if disponible <= 0:
                break
            if s <= UMBRAL_SALDO_CERO:
                continue
            abono = min(disponible, s + calculo[i][0] - pagos[i])
            pagos[i] += abono
            disponible -= abono
        fila, interes_mes = [], CERO
        for i, ((interes, minimo), pago) in enumerate(zip(calculo, pagos)):
            if saldos[i] <= UMBRAL_SALDO_CERO:
                continue
            saldos[i] = saldos[i] + interes - pago
            intereses[i] += interes
            interes_mes += interes
            fila.append((i, pago, pago - minimo, saldos[i]))
            if saldos[i] <= UMBRAL_SALDO_CERO and fin[i] is None:
                fin[i] = mes
        if guardar_calendario:
            sim.calendario.append((mes, fila, interes_mes))
    if all(f is not None for f in fin):
        sim.meses = max(fin, default=0)
    return sim


def simular_base(orden: list[Costo], meses_max: int = MESES_MAX) -> Simulacion:
    """Escenario base: cada deuda paga solo su mínimo hasta liquidarse, sin abonos extra."""
    intereses, fin = [], []
    for k in orden:
        saldo, acumulado, termino = k.candidata.saldo, CERO, None
        for mes in range(1, meses_max + 1):
            interes, minimo = interes_y_minimo(k.candidata, saldo)
            saldo = saldo + interes - minimo
            acumulado += interes
            if saldo <= UMBRAL_SALDO_CERO:
                termino = mes
                break
        intereses.append(acumulado)
        fin.append(termino)
    meses = max(fin, default=0) if all(f is not None for f in fin) else None
    return Simulacion(meses=meses, intereses=intereses, fin=fin)


def extra_sugerido(flujo_minimo: Optional[Decimal]) -> Decimal:
    """Lo que le sobra al usuario en su peor mes (Fórmula 3), redondeado hacia abajo a cientos."""
    if flujo_minimo is None or flujo_minimo <= 0:
        return CERO
    return (flujo_minimo / CIEN).to_integral_value(rounding=ROUND_DOWN) * CIEN


# ------------------------------------------------------------- respuesta
def _c(valor: Decimal) -> Decimal:
    return fechas.a_centavos(valor)


def _dinero(valor: Decimal) -> str:
    return f"${_c(valor):,.2f}"


def _periodo(periodos: list[tuple[int, int]], mes: Optional[int]) -> Optional[str]:
    """AAAA-MM del mes `mes` (1 = el primero de `periodos`), aunque pase del horizonte."""
    if mes is None:
        return None
    anio, m = periodos[0]
    total = anio * 12 + (m - 1) + (mes - 1)
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _meses(n: int) -> str:
    return "1 mes" if n == 1 else f"{n} meses"


def _mensaje(extra: Decimal, total: TotalPlanOut) -> str:
    if total.meses_plan is None:
        return ("Con este presupuesto tus deudas no se terminan de pagar. Revisa tus gastos o "
                "aumenta tu abono extra.")
    con = f"Con {_dinero(extra)} extra al mes" if extra > 0 else "Manteniendo tus pagos de hoy"
    texto = (f"{con} liquidas tus deudas en {_meses(total.meses_plan)} ({total.liquidacion_plan}) "
             f"y pagas {_dinero(total.intereses_plan)} de intereses.")
    if total.meses_base is None:
        return texto + (" Pagando solo el mínimo, alguna de tus deudas nunca se terminaría de "
                        "pagar.")
    return (texto + f" Pagando solo el mínimo tardarías {_meses(total.meses_base)} y pagarías "
            f"{_dinero(total.intereses_base)}: te ahorras {_dinero(total.ahorro)}.")


def armar_plan(orden: list[Costo], extra: Decimal, flujo_minimo: Optional[Decimal],
               periodos: list[tuple[int, int]]) -> Optional[PlanOut]:
    """Plan de pagos con su escenario base (T45). None si no hay deudas en el ranking."""
    if not orden:
        return None
    avisos: list[AvisoPlanOut] = []
    con_pago = [(i + 1, k) for i, k in enumerate(orden) if k.pago_minimo is not None]
    sin_pago = [k for k in orden if k.pago_minimo is None]
    for k in sin_pago:
        avisos.append(AvisoPlanOut(
            codigo="DEUDA_SIN_PAGO_MENSUAL",
            mensaje=f"{k.candidata.nombre} no tiene pago mensual registrado y no entra al plan."))
    if not con_pago:
        return None

    plan_orden = [k for _, k in con_pago]
    plan = simular_plan(plan_orden, extra)
    base = simular_base(plan_orden)

    deudas = []
    for (posicion, k), int_plan, fin_plan, int_base, fin_base in zip(
            con_pago, plan.intereses, plan.fin, base.intereses, base.fin):
        deudas.append(DeudaPlanOut(
            clave=k.candidata.clave, nombre=k.candidata.nombre, posicion=posicion,
            meses_plan=fin_plan, liquidacion_plan=_periodo(periodos, fin_plan),
            intereses_plan=_c(int_plan) if fin_plan is not None else None,
            meses_base=fin_base, liquidacion_base=_periodo(periodos, fin_base),
            intereses_base=_c(int_base) if fin_base is not None else None))

    intereses_plan = _c(sum(plan.intereses, CERO)) if plan.meses is not None else None
    intereses_base = _c(sum(base.intereses, CERO)) if base.meses is not None else None
    # Con los totales ya redondeados, igual que la hoja T26 (CP-12)
    ahorro = (intereses_base - intereses_plan
              if intereses_base is not None and intereses_plan is not None else None)
    meses_menos = (base.meses - plan.meses
                   if base.meses is not None and plan.meses is not None else None)
    total = TotalPlanOut(
        meses_plan=plan.meses, liquidacion_plan=_periodo(periodos, plan.meses),
        intereses_plan=intereses_plan, meses_base=base.meses,
        liquidacion_base=_periodo(periodos, base.meses), intereses_base=intereses_base,
        ahorro=ahorro, meses_menos=meses_menos)

    if base.meses is None:
        avisos.append(AvisoPlanOut(
            codigo="BASE_NO_SE_LIQUIDA",
            mensaje="Pagando solo el mínimo, al menos una deuda nunca se termina de pagar, así "
                    "que el ahorro no se puede calcular completo."))
    if plan.meses is None:
        avisos.append(AvisoPlanOut(
            codigo="PLAN_NO_SE_LIQUIDA",
            mensaje="Con este presupuesto no se terminan de pagar tus deudas. Aumenta tu abono "
                    "extra o revisa tus gastos."))
    if flujo_minimo is not None and flujo_minimo <= 0:                     # REQ-PD-04
        avisos.append(AvisoPlanOut(
            codigo="SIN_DINERO_EXTRA",
            mensaje="Según tu proyección no te sobra dinero al mes para abonar extra. Revisa tus "
                    "gastos antes de comprometer un pago mayor."))
    elif extra > 0 and flujo_minimo is not None and extra > flujo_minimo:  # CE-09
        avisos.append(AvisoPlanOut(
            codigo="EXCEDENTE_NO_SOSTENIBLE",
            mensaje=f"Tu extra ({_dinero(extra)}) es mayor que lo que te sobra en tu peor mes "
                    f"({_dinero(flujo_minimo)}): no podrías mantenerlo todos los meses."))

    claves = [k.candidata.clave for k in plan_orden]
    calendario = []
    for mes, fila, interes_mes in plan.calendario[:CALENDARIO_MAX]:
        pagos = [PagoMesOut(clave=claves[i], pago=_c(p), abono_extra=_c(e),
                            saldo_final=_c(max(s, CERO)))
                 for i, p, e, s in fila]
        calendario.append(MesPlanOut(
            mes=mes, periodo=_periodo(periodos, mes), pagos=pagos,
            total_pagado=_c(sum((p for _, p, _, _ in fila), CERO)), intereses=_c(interes_mes),
            saldo_total=_c(sum((max(s, CERO) for _, _, _, s in fila), CERO))))

    return PlanOut(
        extra_mensual=_c(extra), extra_sugerido=_c(extra_sugerido(flujo_minimo)),
        presupuesto_mensual=_c(presupuesto(plan_orden, extra)), escenario_base="solo_minimo",
        escenario_base_texto=ESCENARIO_BASE_TEXTO, deudas=deudas, total=total,
        calendario=calendario, calendario_completo=len(plan.calendario) <= CALENDARIO_MAX,
        mensaje=_mensaje(extra, total), avisos=avisos, supuestos=SUPUESTOS)