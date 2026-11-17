"""Alertas del usuario (T47): revisión, regla de no repetir, centro de notificaciones y configuración.

La revisión lee lo que ya calculan el balance (T33) y el score (T35); no recalcula nada.

Cuándo una alerta está "activa" y cuándo puede volver a dispararse:
  * Activa: hay una fila `estado='activa'` para (regla, referencia) y la condición se sigue cumpliendo.
    Mientras lo esté, ninguna revisión crea otra fila ni vuelve a avisar, esté leída o no.
  * Resuelta: la condición dejó de cumplirse en una revisión. La fila se conserva como historial.
  * Vuelve a dispararse: si la condición regresa después de resuelta, se crea una alerta nueva.
    Excepción: si se resolvió hace menos de `enfriamiento_horas`, se reactiva la misma fila sin
    avisar otra vez, para que quien oscila alrededor del umbral no reciba el mismo aviso varias veces.
  * Una vez avisada (`notificada_en`), una alerta no se avisa de nuevo.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import ApiError
from app.models import Alerta, AlertaConfiguracion, Usuario
from app.schemas.alerta import (AlertaOut, AlertasOut, CanalesOut, ConfiguracionEditar,
                                ConfiguracionOut, RevisionOut)
from app.services import fechas, formulas, proyeccion
from app.services.alertas_reglas import (Configuracion, DatosAlertas, Hallazgo, MesDatos,
                                         TarjetaDatos, evaluar, reglas_vigentes)
from app.services.comunes import confirmar, obtener_del_usuario

log = logging.getLogger(__name__)
LIMITE_DEFECTO, LIMITE_MAX = 50, 100


@dataclass
class ResultadoRevision:
    nuevas: int = 0
    resueltas: int = 0


def ahora() -> datetime:
    """Hora de México sin zona ni microsegundos (la fecha sale de hoy_mx, que las pruebas fijan)."""
    hora = datetime.now(ZoneInfo(settings.zona_horaria)).time().replace(microsecond=0)
    return datetime.combine(fechas.hoy_mx(), hora)


# ------------------------------------------------------------------ configuración
def _config_fila(db: Session, usuario: Usuario) -> Optional[AlertaConfiguracion]:
    return db.scalar(select(AlertaConfiguracion).where(AlertaConfiguracion.usuario_id == usuario.id))


def config_efectiva(db: Session, usuario: Usuario) -> Configuracion:
    """Lo guardado por el usuario o, si nunca la cambió, los valores por defecto del archivo de reglas."""
    fila = _config_fila(db, usuario)
    d = reglas_vigentes().defecto
    if fila is None:
        return Configuracion(d["umbral_utilizacion"], d["dias_anticipacion"],
                             d["canal_correo"], d["canal_push"])
    return Configuracion(fila.umbral_utilizacion, fila.dias_anticipacion,
                         fila.canal_correo, fila.canal_push)


def _config_out(c: Configuracion) -> ConfiguracionOut:
    return ConfiguracionOut(umbral_utilizacion=c.umbral_utilizacion,
                            dias_anticipacion=c.dias_anticipacion,
                            canales=CanalesOut(correo=c.canal_correo, push=c.canal_push))


def configuracion(db: Session, usuario: Usuario) -> ConfiguracionOut:
    return _config_out(config_efectiva(db, usuario))


def guardar_configuracion(db: Session, usuario: Usuario, datos: ConfiguracionEditar) -> ConfiguracionOut:
    fila = _config_fila(db, usuario)
    if fila is None:
        base = config_efectiva(db, usuario)
        fila = AlertaConfiguracion(usuario_id=usuario.id, umbral_utilizacion=base.umbral_utilizacion,
                                   dias_anticipacion=base.dias_anticipacion,
                                   canal_correo=base.canal_correo, canal_push=base.canal_push)
        db.add(fila)
    cambios = datos.model_dump(exclude_unset=True)
    for campo in ("umbral_utilizacion", "dias_anticipacion"):
        if campo in cambios:
            setattr(fila, campo, cambios[campo])
    canales = cambios.get("canales") or {}
    if "correo" in canales:
        fila.canal_correo = canales["correo"]
    if "push" in canales:
        fila.canal_push = canales["push"]
    confirmar(db, usuario)   # reevalúa las alertas con el umbral nuevo (US 10.2)
    return _config_out(config_efectiva(db, usuario))


# ------------------------------------------------------------------ revisión
def _datos(db: Session, usuario: Usuario) -> DatosAlertas:
    """Arma la entrada de las reglas con el motor de balance (T33): no recalcula fórmulas."""
    from app.services.tarjetas import _pagos_de_estados
    reglas = reglas_vigentes()
    prep = proyeccion.preparar(db, usuario, reglas.horizonte_meses)
    meses: list[MesDatos] = []
    if prep.entrada is not None:
        res = formulas.proyectar(prep.entrada, reglas.horizonte_meses)
        meses = [MesDatos(periodo=f"{p[0]:04d}-{p[1]:02d}", ingresos=m.ingresos,
                          compromisos=m.compromisos)
                 for m, p in zip(res.meses, prep.periodos)]
    pagos = _pagos_de_estados(db, [t.id for t in prep.tarjetas], prep.hoy)
    tarjetas = []
    for t in prep.tarjetas:
        pendiente = sum((formulas.pendiente_msi(p.monto_mensualidad, p.num_mensualidades,
                                                p.mensualidades_pagadas)
                         for p in prep.planes if p.tarjeta_id == t.id), formulas.CERO)
        tarjetas.append(TarjetaDatos(
            id=t.id, nombre=t.nombre, saldo=t.saldo_actual, limite=t.limite_credito,
            pendiente_msi=pendiente,
            fecha_pago=pagos.get(t.id) or fechas.proxima_fecha(t.dia_pago, prep.hoy)))
    return DatosAlertas(hoy=prep.hoy, meses=tuple(meses), tarjetas=tuple(tarjetas))


def _crear(db: Session, usuario: Usuario, h: Hallazgo, momento: datetime) -> bool:
    """Inserta la alerta; si otra petición ganó la carrera, el UNIQUE lo impide y no se duplica."""
    alerta = Alerta(usuario_id=usuario.id, regla=h.regla, referencia=h.referencia,
                    severidad=h.severidad, titulo=h.titulo, mensaje=h.mensaje, accion=h.accion,
                    estado="activa", clave_activa=h.clave, disparada_en=momento)
    try:
        with db.begin_nested():
            db.add(alerta)
            db.flush()
    except IntegrityError:
        return False
    return True


def revisar(db: Session, usuario: Usuario) -> ResultadoRevision:
    """Evalúa las cuatro reglas y deja las alertas del usuario al día. No hace commit."""
    reglas = reglas_vigentes()
    hallazgos = evaluar(_datos(db, usuario), config_efectiva(db, usuario), reglas)
    momento = ahora()
    resultado = ResultadoRevision()

    activas = {a.clave_activa: a for a in db.scalars(select(Alerta).where(
        Alerta.usuario_id == usuario.id, Alerta.estado == "activa"))}
    vigentes: set[str] = set()
    for h in hallazgos:
        vigentes.add(h.clave)
        existente = activas.get(h.clave)
        if existente is not None:
            # Sigue activa: no se duplica ni se vuelve a avisar. Si cambió el texto (p. ej. el mes
            # de AL-01 o el umbral de AL-02), se actualiza en la misma fila.
            existente.titulo, existente.mensaje, existente.accion = h.titulo, h.mensaje, h.accion
            existente.severidad = h.severidad
            continue
        desde = momento - timedelta(hours=reglas.enfriamiento_horas)
        reciente = db.scalar(select(Alerta).where(
            Alerta.usuario_id == usuario.id, Alerta.regla == h.regla,
            Alerta.referencia == h.referencia, Alerta.estado == "resuelta",
            Alerta.resuelta_en >= desde).order_by(Alerta.resuelta_en.desc()).limit(1))
        if reciente is not None:      # oscilación: se reactiva la misma fila, sin aviso nuevo
            reciente.estado, reciente.clave_activa, reciente.resuelta_en = "activa", h.clave, None
            reciente.titulo, reciente.mensaje, reciente.accion = h.titulo, h.mensaje, h.accion
            reciente.severidad = h.severidad
            db.flush()
        elif _crear(db, usuario, h, momento):
            resultado.nuevas += 1

    for clave, alerta in activas.items():
        if clave not in vigentes:
            alerta.estado, alerta.clave_activa, alerta.resuelta_en = "resuelta", None, momento
            resultado.resueltas += 1
    db.flush()
    return resultado


# ------------------------------------------------------------------ centro de notificaciones
def _out(a: Alerta) -> AlertaOut:
    return AlertaOut(id=a.id, regla=a.regla, severidad=a.severidad, titulo=a.titulo,
                     mensaje=a.mensaje, accion=a.accion, referencia=a.referencia, estado=a.estado,
                     leida=a.leida_en is not None, creada_en=a.disparada_en,
                     resuelta_en=a.resuelta_en)


def _sin_leer(db: Session, usuario: Usuario) -> int:
    return db.scalar(select(func.count()).select_from(Alerta).where(
        Alerta.usuario_id == usuario.id, Alerta.estado == "activa",
        Alerta.leida_en.is_(None))) or 0


def listar(db: Session, usuario: Usuario, estado: str = "activa",
           limite: int = LIMITE_DEFECTO) -> AlertasOut:
    consulta = select(Alerta).where(Alerta.usuario_id == usuario.id)
    if estado != "todas":
        consulta = consulta.where(Alerta.estado == estado)
    filas = db.scalars(consulta.order_by(Alerta.disparada_en.desc(), Alerta.id.desc())
                       .limit(limite)).all()
    return AlertasOut(total=len(filas), sin_leer=_sin_leer(db, usuario),
                      alertas=[_out(a) for a in filas])


def marcar_leida(db: Session, usuario: Usuario, alerta_id: int, leida: bool) -> AlertaOut:
    a = obtener_del_usuario(db, Alerta, alerta_id, usuario,
                            ApiError(404, "ALERTA_NO_ENCONTRADA", "La alerta no existe."))
    a.leida_en = (a.leida_en or ahora()) if leida else None
    db.commit()   # no cambia datos financieros: no hace falta recalcular
    return _out(a)


# ------------------------------------------------------------------ revisión diaria (cron)
def revision_diaria(db: Session) -> RevisionOut:
    """Revisa a todos los usuarios, uno por uno: el fallo de uno no detiene a los demás."""
    from app.services import score
    salida = RevisionOut(usuarios_revisados=0, alertas_nuevas=0, alertas_resueltas=0,
                         avisos_enviados=0, errores=0)
    for uid in db.scalars(select(Usuario.id).order_by(Usuario.id)).all():
        try:
            usuario = db.get(Usuario, uid)
            score.guardar_en_historial(db, usuario)
            r = revisar(db, usuario)
            db.commit()
            salida.usuarios_revisados += 1
            salida.alertas_nuevas += r.nuevas
            salida.alertas_resueltas += r.resueltas
            salida.avisos_enviados += _avisar(db, usuario)
        except Exception:   # noqa: BLE001 — se cuenta y se sigue con el siguiente
            db.rollback()
            salida.errores += 1
            log.exception("Falló la revisión diaria del usuario %s", uid)
    return salida


def _avisar(db: Session, usuario: Usuario) -> int:
    """Envía lo pendiente por los canales del usuario (T50); nunca lanza."""
    from app.services import notificaciones
    return notificaciones.enviar_pendientes(db, usuario)
