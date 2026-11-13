"""Priorizador de deudas (T43): ordena las tarjetas y deudas del usuario por costo real y explica,
en dinero, por qué cada una va en su posición. Fórmula 9 de T25 (método avalancha).

No tiene fórmulas propias de interés: la tasa mensual efectiva, el interés del mes y el pago
mínimo son los del motor de cálculo (app/services/formulas.py, Fórmulas 5 y 6), y los datos del
usuario se leen con la misma preparación del balance (T33). Solo lee: no modifica nada.

Reglas de negocio:
- RN-18: el orden es por costo real (tasa, uso del límite e intereses), no por lo que se debe.
- RN-19: las compras a MSI no entran al orden, pero se cuentan como pagos fijos del mes.
- RN-20: primero se cubre el mínimo de todas las deudas; lo extra va a la posición 1.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Usuario
from app.schemas.priorizador import (AvisoOut, BolaDeNieveOut, ComparacionOut, PosicionOut,
                                     PriorizadorOut, SinRankingOut)
from app.services import fechas, formulas, proyeccion
from app.services.formulas import CERO, UMBRAL_SALDO_CERO

MIL = Decimal("1000")
_CIEN = Decimal("100")
_DOCE = Decimal("12")


def _c(valor: Decimal) -> Decimal:
    return fechas.a_centavos(valor)


def _dinero(valor: Decimal) -> str:
    signo = "-" if valor < 0 else ""
    return f"{signo}${abs(_c(valor)):,.2f}"


def _pct(valor: Decimal, decimales: int = 2) -> str:
    return f"{valor * _CIEN:.{decimales}f} %"


# ------------------------------------------------------------- datos (puros)
@dataclass(frozen=True)
class Candidata:
    """Una tarjeta o deuda del usuario, ya con la tasa en decimal (0.60 = 60 %)."""
    tipo: str                                  # "tarjeta" o "deuda"
    id: int
    nombre: str
    saldo: Decimal
    tasa_anual: Optional[Decimal]              # None = no se capturó
    limite: Optional[Decimal] = None           # solo tarjetas
    pendiente_msi: Decimal = CERO              # solo tarjetas: lo que falta de sus MSI
    pago_mensual: Optional[Decimal] = None     # solo deudas

    @property
    def clave(self) -> str:
        return f"{self.tipo}-{self.id}"


@dataclass(frozen=True)
class Costo:
    """Costo real de una deuda (T25, Fórmulas 5 y 6)."""
    candidata: Candidata
    tasa_mensual: Decimal                      # r'
    interes_mes: Decimal
    costo_anual_compuesto: Decimal             # (1 + r')^12 − 1
    utilizacion: Optional[Decimal]             # fracción (0.467 = 46.7 %); None sin límite
    pago_minimo: Optional[Decimal]

    @property
    def ahorro_por_mil(self) -> Decimal:
        """Intereses que deja de generar cada $1,000 abonados a esta deuda, al mes."""
        return MIL * self.tasa_mensual


def tasa_mensual(c: Candidata) -> Decimal:
    """r' de la Fórmula 5. Las tarjetas llevan IVA; las demás deudas usan tasa ÷ 12, igual que
    las otras cuotas de la proyección (T33)."""
    if c.tipo == "tarjeta":
        return formulas.tasa_mensual_efectiva(c.tasa_anual)
    return c.tasa_anual / _DOCE


def costo(c: Candidata) -> Costo:
    r = tasa_mensual(c)
    if c.tipo == "tarjeta":
        interes = formulas.interes_mes(c.saldo, c.tasa_anual)                  # Fórmula 5
        limite = c.limite or CERO
        pago = formulas.pago_minimo(c.saldo, interes, limite)                 # Fórmula 6
        utilizacion = (c.saldo + c.pendiente_msi) / limite if limite > 0 else None
    else:
        interes = c.saldo * r
        pago = None if c.pago_mensual is None else min(c.pago_mensual, c.saldo + interes)
        utilizacion = None
    return Costo(candidata=c, tasa_mensual=r, interes_mes=interes,
                 costo_anual_compuesto=(1 + r) ** 12 - 1, utilizacion=utilizacion,
                 pago_minimo=pago)


def clave_orden(k: Costo) -> tuple:
    """Fórmula 9: mayor r'; si empatan, mayor utilización; si siguen, menor saldo.
    Una deuda sin límite cuenta como utilización 0. El último criterio solo deja el orden
    fijo."""
    return (-k.tasa_mensual, -(k.utilizacion or CERO), k.candidata.saldo,
            k.candidata.tipo, k.candidata.id)


def ordenar(costos: list[Costo]) -> list[Costo]:
    return sorted(costos, key=clave_orden)


def criterio(antes: Costo, despues: Costo) -> str:
    """Qué criterio de la Fórmula 9 separó a dos deudas consecutivas."""
    if antes.tasa_mensual != despues.tasa_mensual:
        return "tasa"
    if (antes.utilizacion or CERO) != (despues.utilizacion or CERO):
        return "utilizacion"
    if antes.candidata.saldo != despues.candidata.saldo:
        return "saldo"
    return "empate"


def _seguir_pagando(k: Costo) -> str:
    """RN-20: lo que se paga a esta deuda mientras se liquida la de la posición 1."""
    if k.pago_minimo is None:
        return "Sigue con su pago normal"
    if k.candidata.tipo == "tarjeta":
        return f"Paga solo el mínimo ({_dinero(k.pago_minimo)})"
    return f"Sigue con su pago mensual ({_dinero(k.pago_minimo)})"


def razon(k: Costo, anterior: Optional[Costo], primera: Costo, total: int) -> str:
    """Por qué la deuda va en su posición, en dinero."""
    c = k.candidata
    base = (f"Con una tasa de {_pct(k.tasa_mensual)} al mes ({_pct(k.costo_anual_compuesto, 1)} "
            f"al año), este mes genera {_dinero(k.interes_mes)} de intereses. Cada $1,000 que le "
            f"abones de más te ahorran {_dinero(k.ahorro_por_mil)} al mes.")
    if anterior is None:
        inicio = ("Es tu única deuda con intereses. " if total == 1
                  else "Es tu deuda más cara: liquídala primero. ")
        return inicio + base
    a = anterior.candidata
    motivo = criterio(anterior, k)
    if motivo == "tasa":
        por_que = (f"Va después de {a.nombre} porque su tasa es menor ({_pct(k.tasa_mensual)} "
                   f"contra {_pct(anterior.tasa_mensual)} al mes): cada $1,000 abonados aquí "
                   f"ahorran {_dinero(anterior.ahorro_por_mil - k.ahorro_por_mil)} menos al mes "
                   f"que en {a.nombre}.")
    elif motivo == "utilizacion":
        uso, uso_antes = _pct(k.utilizacion or CERO, 1), _pct(anterior.utilizacion or CERO, 1)
        por_que = (f"Tiene la misma tasa que {a.nombre}, pero usa menos de su límite ({uso} "
                   f"contra {uso_antes}), y una tarjeta muy usada baja más tu score.")
    elif motivo == "saldo":
        por_que = (f"Tiene la misma tasa y el mismo uso que {a.nombre}, pero debes más "
                   f"({_dinero(c.saldo)} contra {_dinero(a.saldo)}): {a.nombre} se liquida antes "
                   "y libera su pago.")
    else:
        por_que = f"Cuesta lo mismo que {a.nombre}; el orden entre las dos no cambia nada."
    return (f"{por_que} {_seguir_pagando(k)} hasta liquidar {primera.candidata.nombre}. "
            f"Este mes genera {_dinero(k.interes_mes)} de intereses.")


def avisos(k: Costo) -> list[AvisoOut]:
    c, salida = k.candidata, []
    if c.tipo == "tarjeta" and not c.limite:
        salida.append(AvisoOut(
            codigo="LIMITE_CERO",
            mensaje="Registra el límite de la tarjeta para saber cuánto de él usas."))
    elif k.utilizacion is not None and k.utilizacion > 1:
        salida.append(AvisoOut(
            codigo="SOBRE_LIMITE",
            mensaje=f"Debes más que tu límite ({_pct(k.utilizacion, 1)} usado)."))
    if c.tipo == "deuda" and c.pago_mensual is None:
        salida.append(AvisoOut(codigo="SIN_PAGO_MENSUAL",
                               mensaje="Registra su pago mensual para incluirlo en tu plan."))
    elif c.tipo == "deuda" and c.pago_mensual is not None and c.pago_mensual <= k.interes_mes:
        salida.append(AvisoOut(codigo="PAGO_NO_CUBRE_INTERES",
                               mensaje="Con su pago mensual la deuda nunca se liquida: no alcanza "
                                       "ni para los intereses."))
    return salida


def bola_de_nieve(orden: list[Costo]) -> Optional[BolaDeNieveOut]:
    """Compara con pagar primero la deuda más chica (el consejo popular)."""
    if len(orden) < 2:
        return None
    chica = min(orden, key=lambda k: (k.candidata.saldo, clave_orden(k)))
    primera = orden[0]
    diferencia = primera.ahorro_por_mil - chica.ahorro_por_mil
    if chica is primera:
        mensaje = (f"{primera.candidata.nombre} es también tu deuda más chica: pagarla primero "
                   "es lo más barato y además la liquidas antes.")
    else:
        mensaje = (f"Mucha gente paga primero la deuda más chica ({chica.candidata.nombre}), pero "
                   f"te sale más caro: cada $1,000 abonados a {chica.candidata.nombre} en lugar "
                   f"de {primera.candidata.nombre} dejan {_dinero(diferencia)} más de intereses "
                   "cada mes.")
    return BolaDeNieveOut(coincide=chica is primera, mas_chica=chica.candidata.clave,
                          mas_chica_nombre=chica.candidata.nombre,
                          diferencia_por_mil=_c(diferencia), mensaje=mensaje)


def separar(candidatas: list[Candidata]) -> tuple[list[Costo], list[SinRankingOut]]:
    """Las que entran al orden y las que no, con su motivo."""
    entran, fuera = [], []
    for c in candidatas:
        motivo = mensaje = None
        if c.saldo <= UMBRAL_SALDO_CERO:
            motivo, mensaje = "SIN_SALDO", "No debes nada en ella: no te cuesta intereses."
        elif c.tasa_anual is None:
            motivo, mensaje = ("SIN_TASA", "Registra su tasa de interés para saber cuánto te "
                                           "cuesta y ordenarla.")
        elif c.tasa_anual == 0:
            motivo, mensaje = ("SIN_INTERESES", "No te cobra intereses: sigue pagando su cuota "
                                                "normal.")
        if motivo:
            fuera.append(SinRankingOut(clave=c.clave, tipo=c.tipo, id=c.id, nombre=c.nombre,
                                       saldo=_c(c.saldo),
                                       pago_mensual=None if c.pago_mensual is None
                                       else _c(c.pago_mensual),
                                       motivo=motivo, mensaje=mensaje))
        else:
            entran.append(costo(c))
    return entran, fuera


def posiciones(orden: list[Costo]) -> list[PosicionOut]:
    salida = []
    for i, k in enumerate(orden):
        c = k.candidata
        anterior = orden[i - 1] if i else None
        comparacion = None
        if anterior is not None:
            comparacion = ComparacionOut(
                contra=anterior.candidata.clave, contra_nombre=anterior.candidata.nombre,
                criterio=criterio(anterior, k),
                ahorro_por_mil_menos=_c(anterior.ahorro_por_mil - k.ahorro_por_mil))
        salida.append(PosicionOut(
            posicion=i + 1, clave=c.clave, tipo=c.tipo, id=c.id, nombre=c.nombre,
            saldo=_c(c.saldo), tasa_anual=float(_c(c.tasa_anual * _CIEN)),
            tasa_mensual=float(_c(k.tasa_mensual * _CIEN)),
            costo_anual_compuesto=float(_c(k.costo_anual_compuesto * _CIEN)),
            interes_mes=_c(k.interes_mes),
            utilizacion=None if k.utilizacion is None else float(_c(k.utilizacion * _CIEN)),
            pago_minimo=None if k.pago_minimo is None else _c(k.pago_minimo),
            ahorro_por_mil=_c(k.ahorro_por_mil),
            accion="abonar_extra" if i == 0 else "pagar_minimo",
            razon=razon(k, anterior, orden[0], len(orden)), comparacion=comparacion,
            avisos=avisos(k)))
    return salida


def resumen(orden: list[Costo], minimos: Decimal, msi_mes: Decimal) -> str:
    """Qué hacer este mes (RN-20)."""
    msi = f", más {_dinero(msi_mes)} de tus MSI" if msi_mes > 0 else ""
    if not orden:
        if msi_mes > 0:
            return (f"No tienes deudas que te cobren intereses. Sigue pagando tus MSI "
                    f"({_dinero(msi_mes)} este mes).")
        return "No tienes deudas que te cobren intereses."
    if len(orden) == 1:
        return (f"Cubre el pago de {orden[0].candidata.nombre} ({_dinero(minimos)}{msi}) y, si te "
                "sobra dinero, abónalo ahí mismo.")
    return (f"Primero cubre el mínimo de todas tus deudas ({_dinero(minimos)} en total este "
            f"mes{msi}). Todo el dinero extra que puedas, abónalo a {orden[0].candidata.nombre}.")


# ---------------------------------------------------------- con la base de datos
def _tasa(valor) -> Optional[Decimal]:
    """La base guarda la tasa en porcentaje (45.5); aquí se usa en decimal (0.455)."""
    return None if valor is None else Decimal(valor) / _CIEN


def candidatas(prep: proyeccion.Preparacion) -> list[Candidata]:
    """Tarjetas activas y deudas activas del usuario. Las deudas liquidadas no llegan aquí."""
    pendientes: dict[int, Decimal] = {}
    for p in prep.planes:
        pendientes[p.tarjeta_id] = pendientes.get(p.tarjeta_id, CERO) + formulas.pendiente_msi(
            p.monto_mensualidad, p.num_mensualidades, p.mensualidades_pagadas)
    salida = [Candidata(tipo="tarjeta", id=t.id, nombre=t.nombre, saldo=t.saldo_actual,
                        tasa_anual=_tasa(t.tasa_anual), limite=t.limite_credito,
                        pendiente_msi=pendientes.get(t.id, CERO))
              for t in prep.tarjetas]
    salida += [Candidata(tipo="deuda", id=d.id, nombre=d.nombre, saldo=d.saldo_actual,
                         tasa_anual=_tasa(d.tasa_anual), pago_mensual=d.pago_mensual)
               for d in prep.deudas]
    return salida


def _msi(prep: proyeccion.Preparacion) -> tuple[list[SinRankingOut], Decimal]:
    """RN-19: los MSI no se ordenan, pero su mensualidad es un pago fijo del mes."""
    salida, total = [], CERO
    for p in prep.planes:
        if not formulas.msi_activo_en_mes(p.num_mensualidades, p.mensualidades_pagadas, 1):
            continue
        total += p.monto_mensualidad
        pendiente = formulas.pendiente_msi(p.monto_mensualidad, p.num_mensualidades,
                                           p.mensualidades_pagadas)
        salida.append(SinRankingOut(
            clave=f"msi-{p.id}", tipo="msi", id=p.id, nombre=p.descripcion, saldo=_c(pendiente),
            pago_mensual=_c(p.monto_mensualidad), motivo="MSI",
            mensaje="Es a meses sin intereses: no te cobra intereses si pagas la mensualidad a "
                    "tiempo, así que no entra al orden (RN-19)."))
    return salida, total


def priorizar(db: Session, usuario: Usuario) -> PriorizadorOut:
    """Ranking de deudas por costo real con la razón de cada posición (T43)."""
    prep = proyeccion.preparar(db, usuario, formulas.HORIZONTE_MIN)
    entran, fuera = separar(candidatas(prep))
    orden = ordenar(entran)
    msi, msi_mes = _msi(prep)
    minimos = sum((k.pago_minimo for k in orden if k.pago_minimo is not None), CERO)

    supuestos = ["El orden sigue el método avalancha de T25 (Fórmula 9): primero la tasa mensual "
                 "más alta, luego la tarjeta más usada y luego la de menor saldo.",
                 "Los intereses del mes se calculan con el saldo actual; en las tarjetas la tasa "
                 "incluye 16 % de IVA."]
    if any(k.candidata.tipo == "deuda" for k in orden):
        supuestos.append("En préstamos y otras deudas la tasa mensual es la tasa anual entre 12, "
                         "igual que en la proyección.")

    return PriorizadorOut(
        estado="calculado" if orden else "sin_deudas", periodo=prep.mes_inicio,
        ranking=posiciones(orden), sin_ranking=fuera + msi,
        resumen=resumen(orden, minimos, msi_mes),
        intereses_mes_total=_c(sum((k.interes_mes for k in orden), CERO)),
        pagos_minimos_total=_c(minimos), msi_mes_total=_c(msi_mes),
        bola_de_nieve=bola_de_nieve(orden), supuestos=supuestos)