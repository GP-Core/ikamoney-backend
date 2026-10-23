"""Balance del mes y proyección de los meses siguientes (T33).

Lee de la base de datos los ingresos, gastos, tarjetas, planes MSI y deudas del usuario de la
sesión, los convierte en las variables de entrada de T25 y aplica las fórmulas de
app/services/formulas.py. Solo lee: no modifica nada ni llama a recalcular().
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Deuda, Gasto, Ingreso, PlanMsi, Tarjeta, Usuario
from app.schemas.proyeccion import (AvisoOut, MesOut, ProyeccionOut, ResumenOut,
                                    SupuestosOut, TarjetaMesOut)
from app.services import fechas, formulas
from app.services.formulas import (CERO, DeudaEntrada, EntradaProyeccion, MsiEntrada,
                                   TarjetaEntrada)

_CIEN = Decimal("100")
NOTA = ("Las cifras son estimaciones: los intereses se calculan con el saldo al corte y no con "
        "el saldo promedio diario, y no se incluyen compras nuevas con tarjeta.")


# ------------------------------------------------------------- utilidades
def _periodos(anio: int, mes: int, n: int) -> list[tuple[int, int]]:
    """n meses consecutivos a partir de (anio, mes)."""
    salida = []
    for _ in range(n):
        salida.append((anio, mes))
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    return salida


def _anteriores(anio: int, mes: int, n: int) -> list[tuple[int, int]]:
    """Los n meses previos a (anio, mes), del más antiguo al más reciente."""
    salida = []
    for _ in range(n):
        anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
        salida.insert(0, (anio, mes))
    return salida


def _total_en_mes(registros, anio: int, mes: int) -> Decimal:
    """Suma de un grupo de ingresos o gastos en un mes, contando cada vez que cae un recurrente."""
    total = CERO
    for r in registros:
        veces = len(fechas.ocurrencias_en_mes(r.frecuencia, r.fecha_inicio, r.fecha_fin, anio, mes))
        total += r.monto * veces
    return total


def _tasa(valor) -> Decimal:
    """La base guarda la tasa en porcentaje (45.5); las fórmulas la usan en decimal (0.455)."""
    return CERO if valor is None else Decimal(valor) / _CIEN


def _c(valor: Decimal) -> Decimal:
    return fechas.a_centavos(valor)


# ------------------------------------------------------------- consultas
def _datos_usuario(db: Session, usuario: Usuario):
    ingresos = db.scalars(select(Ingreso).where(
        Ingreso.usuario_id == usuario.id, Ingreso.activo.is_(True))).all()
    gastos = db.scalars(select(Gasto).where(
        Gasto.usuario_id == usuario.id, Gasto.activo.is_(True))).all()
    tarjetas = db.scalars(select(Tarjeta).where(
        Tarjeta.usuario_id == usuario.id, Tarjeta.activa.is_(True)).order_by(Tarjeta.id)).all()
    # plan_msi no tiene usuario_id (T18 §4.1): el dueño se obtiene por la tarjeta.
    planes = db.scalars(select(PlanMsi).join(Tarjeta, PlanMsi.tarjeta_id == Tarjeta.id).where(
        Tarjeta.usuario_id == usuario.id, PlanMsi.estatus == "activo").order_by(PlanMsi.id)).all()
    deudas = db.scalars(select(Deuda).where(
        Deuda.usuario_id == usuario.id, Deuda.estatus == "activa").order_by(Deuda.id)).all()
    return ingresos, gastos, tarjetas, planes, deudas


# ------------------------------------------------------------- respuesta
def _mes_out(m: formulas.MesProyectado, periodo: tuple[int, int]) -> MesOut:
    return MesOut(
        mes=m.mes, periodo=f"{periodo[0]:04d}-{periodo[1]:02d}",
        ingresos=_c(m.ingresos), gastos_fijos=_c(m.gastos_fijos),
        gastos_variables=_c(m.gastos_variables), pagos_tarjetas=_c(m.pagos_tarjetas),
        mensualidades_msi=_c(m.mensualidades_msi), otras_cuotas=_c(m.otras_cuotas),
        compromisos=_c(m.compromisos), flujo=_c(m.flujo), acumulado=_c(m.acumulado),
        saldo_tarjetas=_c(m.saldo_tarjetas), msi_activos=m.msi_activos,
        tarjetas=[TarjetaMesOut(tarjeta_id=t.tarjeta_id, nombre=t.nombre,
                                saldo_inicio=_c(t.saldo_inicio), interes=_c(t.interes),
                                pago=_c(t.pago), saldo_fin=_c(t.saldo_fin))
                  for t in m.tarjetas])


def calcular(db: Session, usuario: Usuario, meses: int = formulas.HORIZONTE_DEFECTO,
             ahorro_inicial: Decimal = CERO) -> ProyeccionOut:
    """Balance del mes en curso (mes 1) y proyección de `meses` meses (T25, Fórmulas 1 a 3)."""
    hoy = fechas.hoy_mx()
    periodos = _periodos(hoy.year, hoy.month, meses)
    mes_inicio = f"{hoy.year:04d}-{hoy.month:02d}"
    ingresos, gastos, tarjetas, planes, deudas = _datos_usuario(db, usuario)
    fijos = [g for g in gastos if g.tipo == "fijo"]
    variables = [g for g in gastos if g.tipo == "variable"]

    # Gastos variables: promedio de los últimos 3 meses con registros (T25). En cada mes se toma
    # lo mayor entre ese promedio y lo que ya esté registrado para ese mes.
    previos = [_total_en_mes(variables, a, m) for a, m in _anteriores(hoy.year, hoy.month, 3)]
    registrados = [_total_en_mes(variables, a, m) for a, m in periodos]
    estimado = formulas.estimar_gastos_variables(previos)
    if estimado is not None:
        base = "promedio_3_meses"
    elif registrados[0] > 0:
        estimado, base = registrados[0], "registrado"
    else:
        estimado, base = CERO, "sin_registros"

    supuestos = SupuestosOut(ahorro_inicial=_c(ahorro_inicial),
                             gastos_variables_estimados=_c(estimado),
                             base_gastos_variables=base, pago_tarjetas="minimo", nota=NOTA)

    # Usuario recién registrado: nada que proyectar (REQ-BP-05 pide una guía, no gráficas vacías)
    if not (ingresos or gastos or tarjetas or planes or deudas):
        return ProyeccionOut(
            estado="sin_datos", mes_inicio=mes_inicio, meses=meses,
            avisos=[AvisoOut(codigo="SIN_DATOS",
                             mensaje="Registra tus ingresos, gastos, tarjetas y deudas para ver tu "
                                     "balance y tu proyección.")],
            supuestos=supuestos, balance_mes=None, proyeccion=[], resumen=None)

    entrada = EntradaProyeccion(
        ingresos=[_total_en_mes(ingresos, a, m) for a, m in periodos],
        gastos_fijos=[_total_en_mes(fijos, a, m) for a, m in periodos],
        gastos_variables=[max(r, estimado) for r in registrados],
        ahorro_inicial=ahorro_inicial,
        tarjetas=[TarjetaEntrada(id=t.id, nombre=t.nombre, saldo=t.saldo_actual,
                                 limite=t.limite_credito, tasa_anual=_tasa(t.tasa_anual))
                  for t in tarjetas],
        planes_msi=[MsiEntrada(id=p.id, descripcion=p.descripcion, monto=p.monto_original,
                               plazo=p.num_mensualidades, pagadas=p.mensualidades_pagadas,
                               mensualidad=p.monto_mensualidad)
                    for p in planes],
        deudas=[DeudaEntrada(id=d.id, nombre=d.nombre, saldo=d.saldo_actual,
                             pago_mensual=d.pago_mensual or CERO, tasa_anual=_tasa(d.tasa_anual))
                for d in deudas])
    resultado = formulas.proyectar(entrada, meses)

    # Avisos (casos especiales de T25 y datos incompletos)
    avisos: list[AvisoOut] = []
    estado = "completo"
    if sum(entrada.ingresos, CERO) == 0:  # CE-03
        estado = "sin_ingresos"
        avisos.append(AvisoOut(codigo="SIN_INGRESOS",
                               mensaje="No tienes ingresos registrados. Captúralos para que el "
                                       "balance y la proyección sean reales."))
    sin_tasa = [t.nombre for t in tarjetas if t.tasa_anual is None]
    if sin_tasa:
        avisos.append(AvisoOut(codigo="TARJETA_SIN_TASA",
                               mensaje="Se calcularon sin intereses porque no tienen tasa: "
                                       + ", ".join(sin_tasa) + "."))
    sin_pago = [d.nombre for d in deudas if d.pago_mensual is None]
    if sin_pago:
        avisos.append(AvisoOut(codigo="DEUDA_SIN_PAGO_MENSUAL",
                               mensaje="No se descuenta ningún pago de: " + ", ".join(sin_pago)
                                       + ". Registra su pago mensual."))
    negativos = [m.mes for m in resultado.meses if m.acumulado < 0]
    if negativos:
        avisos.append(AvisoOut(codigo="SALDO_NEGATIVO",
                               mensaje=f"Tu dinero no alcanza a partir del mes {negativos[0]} "
                                       f"({periodos[negativos[0] - 1][0]:04d}-"
                                       f"{periodos[negativos[0] - 1][1]:02d})."))

    proyeccion = [_mes_out(m, periodos[m.mes - 1]) for m in resultado.meses]
    peor = min(resultado.meses, key=lambda m: (m.flujo, m.mes))
    resumen = ResumenOut(flujo_minimo=_c(resultado.flujo_minimo), mes_flujo_minimo=peor.mes,
                         acumulado_minimo=_c(resultado.acumulado_minimo),
                         meses_en_negativo=resultado.meses_en_negativo,
                         saldo_tarjetas_final=_c(resultado.meses[-1].saldo_tarjetas))
    return ProyeccionOut(estado=estado, mes_inicio=mes_inicio, meses=meses, avisos=avisos,
                         supuestos=supuestos, balance_mes=proyeccion[0], proyeccion=proyeccion,
                         resumen=resumen)