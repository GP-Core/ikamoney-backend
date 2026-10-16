"""Tarjetas de crédito: saldo, tasa, límite y fechas de corte y pago (T17 §4.3)."""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errores import ApiError
from app.models import EstadoCuenta, PlanMsi, Tarjeta, Usuario
from app.schemas.tarjeta import (TarjetaCrear, TarjetaEditar, TarjetaEliminadaOut,
                                 TarjetaOut)
from app.services import fechas
from app.services.comunes import confirmar, obtener_del_usuario


def obtener(db: Session, usuario: Usuario, tarjeta_id: int) -> Tarjeta:
    """Id inexistente o de otro usuario => 404 (T17 §3)."""
    return obtener_del_usuario(db, Tarjeta, tarjeta_id, usuario,
                               ApiError(404, "TARJETA_NO_ENCONTRADA", "La tarjeta no existe."))


def _pagos_de_estados(db: Session, ids: list[int], hoy: date) -> dict[int, date]:
    """Fecha límite de pago real más cercana (T18 §4.3: el estado manda sobre la regla)."""
    if not ids:
        return {}
    filas = db.execute(
        select(EstadoCuenta.tarjeta_id, func.min(EstadoCuenta.fecha_limite_pago))
        .where(EstadoCuenta.tarjeta_id.in_(ids), EstadoCuenta.fecha_limite_pago >= hoy)
        .group_by(EstadoCuenta.tarjeta_id)
    ).all()
    return {tarjeta_id: fecha for tarjeta_id, fecha in filas}


def a_out(t: Tarjeta, hoy: date, pagos: dict[int, date]) -> TarjetaOut:
    """Arma la respuesta con los campos derivados (disponible, % usado, próximas fechas)."""
    if t.limite_credito > 0:
        pct = round(float(t.saldo_actual / t.limite_credito * 100), 2)
    else:
        pct = 100.0 if t.saldo_actual > 0 else 0.0
    return TarjetaOut(
        id=t.id, nombre=t.nombre, banco=t.banco, ultimos_4=t.ultimos_4,
        limite_credito=t.limite_credito, saldo_actual=t.saldo_actual,
        credito_disponible=max(t.limite_credito - t.saldo_actual, Decimal("0.00")),
        porcentaje_limite_usado=pct, dia_corte=t.dia_corte, dia_pago=t.dia_pago,
        tasa_anual=t.tasa_anual, activa=t.activa,
        proxima_fecha_corte=fechas.proxima_fecha(t.dia_corte, hoy),
        proxima_fecha_pago=pagos.get(t.id) or fechas.proxima_fecha(t.dia_pago, hoy),
    )


def _out(db: Session, t: Tarjeta) -> TarjetaOut:
    hoy = fechas.hoy_mx()
    return a_out(t, hoy, _pagos_de_estados(db, [t.id], hoy))


def listar(db: Session, usuario: Usuario, activa: Optional[bool] = None) -> list[TarjetaOut]:
    consulta = select(Tarjeta).where(Tarjeta.usuario_id == usuario.id).order_by(Tarjeta.id)
    if activa is not None:
        consulta = consulta.where(Tarjeta.activa == activa)
    tarjetas = db.scalars(consulta).all()
    hoy = fechas.hoy_mx()
    pagos = _pagos_de_estados(db, [t.id for t in tarjetas], hoy)
    return [a_out(t, hoy, pagos) for t in tarjetas]


def crear(db: Session, usuario: Usuario, datos: TarjetaCrear) -> TarjetaOut:
    t = Tarjeta(usuario_id=usuario.id, **datos.model_dump())
    db.add(t)
    confirmar(db, usuario)
    return _out(db, t)


def detalle(db: Session, usuario: Usuario, tarjeta_id: int) -> TarjetaOut:
    return _out(db, obtener(db, usuario, tarjeta_id))


def editar(db: Session, usuario: Usuario, tarjeta_id: int, datos: TarjetaEditar) -> TarjetaOut:
    t = obtener(db, usuario, tarjeta_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(t, campo, valor)
    confirmar(db, usuario)
    return _out(db, t)


def eliminar(db: Session, usuario: Usuario, tarjeta_id: int) -> TarjetaEliminadaOut:
    t = obtener(db, usuario, tarjeta_id)
    n_msi = db.scalar(select(func.count()).select_from(PlanMsi).where(PlanMsi.tarjeta_id == t.id))
    db.delete(t)  # ON DELETE CASCADE borra estados, movimientos y planes MSI
    confirmar(db, usuario)
    return TarjetaEliminadaOut(id=tarjeta_id, planes_msi_eliminados=n_msi or 0)
