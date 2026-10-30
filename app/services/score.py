"""Índice de Salud Financiera del usuario de la sesión (T35).

Toma los datos del usuario con el mismo motor del balance (T33), calcula el score con
app/services/score_formulas.py y las reglas de app/core/reglas_score.json, y guarda una foto
en score_historial cada vez que cambia (lo llama recalcular() en cada alta, cambio o baja).
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ScoreHistorial, Usuario
from app.schemas.score import (FactorOut, FaltanteOut, HistorialOut, PuntoHistorialOut,
                               ScoreOut)
from app.services import formulas, proyeccion
from app.services.formulas import CERO
from app.services.score_formulas import (EntradaScore, ResultadoScore, calcular as calcular_score,
                                         nivel_de)
from app.services.score_reglas import ReglasScore, reglas_vigentes

HISTORIAL_DEFECTO = 12
HISTORIAL_MAX = 24

TEXTO_COMPORTAMIENTO = {
    "pago_total": "pagas el total",
    "mas_del_minimo": "pagas más del mínimo",
    "solo_minimo": "pagas solo el mínimo",
    "con_atraso": "pagas con atraso",
}


def _f(valor: Optional[Decimal], decimales: str = "0.01") -> Optional[float]:
    if valor is None:
        return None
    return float(Decimal(valor).quantize(Decimal(decimales), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------ datos de entrada
def _evaluar(db: Session, usuario: Usuario, reglas: ReglasScore):
    """Devuelve (periodo, resultado o None, faltantes, supuestos)."""
    prep = proyeccion.preparar(db, usuario, formulas.HORIZONTE_MIN)
    periodo = prep.mes_inicio
    faltantes: list[FaltanteOut] = []

    mes1 = formulas.proyectar(prep.entrada, formulas.HORIZONTE_MIN).meses[0] if prep.entrada else None
    if mes1 is None or mes1.ingresos <= 0:                                     # CE-03
        mensaje = ("Registra tu ingreso neto mensual (sueldo, honorarios u otros) para calcular "
                   "tu score." if not prep.ingresos else
                   "Ninguno de tus ingresos cae en este mes. Registra tu ingreso mensual para "
                   "calcular tu score.")
        faltantes.append(FaltanteOut(dato="ingresos", obligatorio=True, mensaje=mensaje))
    if not prep.gastos:
        faltantes.append(FaltanteOut(
            dato="gastos", obligatorio=False,
            mensaje="Registra tus gastos fijos y variables: sin ellos tu flujo libre se ve mejor "
                    "de lo que es."))
    if any(f.obligatorio for f in faltantes):
        return periodo, None, faltantes, []

    activas = {t.id for t in prep.tarjetas}
    pendiente = sum((formulas.pendiente_msi(p.monto_mensualidad, p.num_mensualidades,
                                            p.mensualidades_pagadas)
                     for p in prep.planes if p.tarjeta_id in activas), CERO)
    comportamiento = reglas.comportamiento_por_defecto
    entrada = EntradaScore(
        ingreso=mes1.ingresos, compromisos=mes1.compromisos,
        mensualidades_msi=mes1.mensualidades_msi, flujo=mes1.flujo,
        saldo_tarjetas=sum((t.saldo_actual for t in prep.tarjetas), CERO),
        pendiente_msi=pendiente,
        limite_total=sum((t.limite_credito for t in prep.tarjetas), CERO),
        comportamiento_pago=comportamiento)

    supuestos = [f"Se considera que {TEXTO_COMPORTAMIENTO[comportamiento]} de tus tarjetas "
                 "(supuesto de T25), porque todavía no se captura tu forma de pago."]
    if entrada.limite_total <= 0:
        supuestos.append("No tienes tarjetas: la utilización de crédito no se toma en cuenta y su "
                         "peso se reparte entre los demás factores (regla 3 de T25).")
    if prep.base_gastos_variables == "promedio_3_meses":
        supuestos.append("Tus gastos variables se estiman con el promedio de los últimos 3 meses "
                         "que tienen registros.")
    return periodo, calcular_score(entrada, reglas), faltantes, supuestos


# ------------------------------------------------------------------ GET /score
def _factor_out(f) -> FactorOut:
    datos = {k: (v if isinstance(v, str) else _f(v)) for k, v in f.datos.items()}
    return FactorOut(
        clave=f.clave, nombre=f.nombre, formula=f.formula, disponible=f.disponible,
        peso=_f(f.peso), peso_efectivo=_f(f.peso_efectivo), valor=_f(f.valor),
        categoria=f.categoria, subpuntaje=_f(f.subpuntaje), aporte=_f(f.aporte),
        puntos_perdidos=_f(f.puntos_perdidos), explicacion=f.explicacion,
        como_mejorar=f.como_mejorar, justificacion_peso=f.justificacion_peso, datos=datos)


def calcular(db: Session, usuario: Usuario) -> ScoreOut:
    """Score del mes en curso con su nivel y su desglose; o la lista de datos que faltan."""
    reglas = reglas_vigentes()
    periodo, r, faltantes, supuestos = _evaluar(db, usuario, reglas)
    if r is None:
        return ScoreOut(estado="datos_faltantes", puntaje=None, puntaje_bruto=None, nivel=None,
                        nivel_texto=None, tope_aplicado=False, motivo_tope=None, periodo=periodo,
                        version_modelo=reglas.version_modelo, factores=[], orden_mejora=[],
                        faltantes=faltantes, supuestos=[])
    return ScoreOut(estado="calculado", puntaje=r.puntaje, puntaje_bruto=_f(r.puntaje_bruto),
                    nivel=r.nivel, nivel_texto=r.nivel_texto, tope_aplicado=r.tope_aplicado,
                    motivo_tope=r.motivo_tope, periodo=periodo, version_modelo=r.version_modelo,
                    factores=[_factor_out(f) for f in r.factores], orden_mejora=r.orden_mejora,
                    faltantes=faltantes, supuestos=supuestos)


# ------------------------------------------------------------------ historial
def _componentes(r: ResultadoScore) -> dict:
    return {
        "nivel": r.nivel,
        "puntaje_bruto": _f(r.puntaje_bruto),
        "motivo_tope": r.motivo_tope,
        "factores": [{"clave": f.clave, "valor": _f(f.valor), "categoria": f.categoria,
                      "subpuntaje": _f(f.subpuntaje), "peso_efectivo": _f(f.peso_efectivo),
                      "aporte": _f(f.aporte)} for f in r.factores],
    }


def _ahora() -> datetime:
    """Fecha de hoy (hora de México) con la hora actual, sin zona y sin microsegundos."""
    hora = datetime.now(ZoneInfo(settings.zona_horaria)).time().replace(microsecond=0)
    return datetime.combine(proyeccion.fechas.hoy_mx(), hora)


def guardar_en_historial(db: Session, usuario: Usuario) -> Optional[ScoreHistorial]:
    """Recalcula el score y agrega una fila si cambió respecto a la última (o si cambió el mes).
    Sin score (faltan datos) no se guarda nada. Las filas nunca se modifican (T18)."""
    reglas = reglas_vigentes()
    _, r, _, _ = _evaluar(db, usuario, reglas)
    if r is None:
        return None
    ahora = _ahora()
    componentes = _componentes(r)
    ultima = db.scalar(select(ScoreHistorial).where(ScoreHistorial.usuario_id == usuario.id)
                       .order_by(ScoreHistorial.calculado_en.desc(), ScoreHistorial.id.desc())
                       .limit(1))
    if (ultima is not None and ultima.puntaje == r.puntaje
            and ultima.version_modelo == r.version_modelo and ultima.componentes == componentes
            and (ultima.calculado_en.year, ultima.calculado_en.month) == (ahora.year, ahora.month)):
        return None
    fila = ScoreHistorial(usuario_id=usuario.id, calculado_en=ahora, puntaje=r.puntaje,
                          version_modelo=r.version_modelo, componentes=componentes)
    db.add(fila)
    return fila


def historial(db: Session, usuario: Usuario, meses: int = HISTORIAL_DEFECTO) -> HistorialOut:
    """Último score de cada mes, de los `meses` meses más recientes (REQ-SF-06)."""
    hoy = proyeccion.fechas.hoy_mx()
    anio, mes = hoy.year, hoy.month
    for _ in range(meses - 1):
        anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    desde = datetime.combine(date(anio, mes, 1), datetime.min.time())
    filas = db.scalars(select(ScoreHistorial)
                       .where(ScoreHistorial.usuario_id == usuario.id,
                              ScoreHistorial.calculado_en >= desde)
                       .order_by(ScoreHistorial.calculado_en, ScoreHistorial.id)).all()
    por_mes: dict[str, ScoreHistorial] = {}
    for fila in filas:                         # en orden: la última de cada mes se queda
        por_mes[f"{fila.calculado_en.year:04d}-{fila.calculado_en.month:02d}"] = fila
    puntos = []
    for periodo, fila in sorted(por_mes.items()):
        nivel, texto = nivel_de(fila.puntaje)
        puntos.append(PuntoHistorialOut(periodo=periodo, puntaje=fila.puntaje, nivel=nivel,
                                        nivel_texto=texto, calculado_en=fila.calculado_en,
                                        version_modelo=fila.version_modelo))
    return HistorialOut(meses=meses, puntos=puntos)