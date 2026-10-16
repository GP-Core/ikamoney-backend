from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services import fechas
from app.core.database import get_db
from app.core.errores import ApiError
from app.models import EstadoCuenta, PlanMsi, Tarjeta, Usuario
from app.services.recalculo import recalcular
from app.schemas.finanzas import (TarjetaCrear, TarjetaEditar, TarjetaEliminadaOut,
                         TarjetaOut)
from app.core.seguridad import usuario_actual

router = APIRouter(prefix="/tarjetas", tags=["Tarjetas"])


def tarjeta_del_usuario(db: Session, usuario: Usuario, tarjeta_id: int) -> Tarjeta:
    """Id inexistente o de otro usuario => 404 (T17 §3)."""
    t = db.scalar(select(Tarjeta).where(Tarjeta.id == tarjeta_id, Tarjeta.usuario_id == usuario.id))
    if t is None:
        raise ApiError(404, "TARJETA_NO_ENCONTRADA", "La tarjeta no existe.")
    return t


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


def _a_out(t: Tarjeta, hoy: date, pagos: dict[int, date]) -> TarjetaOut:
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
    return _a_out(t, hoy, _pagos_de_estados(db, [t.id], hoy))


@router.get("", response_model=list[TarjetaOut],
            summary="Lista con saldo, porcentaje del límite usado y próxima fecha de pago")
def listar(activa: Optional[bool] = Query(None, description="Filtra por activas/inactivas"),
           db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    consulta = select(Tarjeta).where(Tarjeta.usuario_id == usuario.id).order_by(Tarjeta.id)
    if activa is not None:
        consulta = consulta.where(Tarjeta.activa == activa)
    tarjetas = db.scalars(consulta).all()
    hoy = fechas.hoy_mx()
    pagos = _pagos_de_estados(db, [t.id for t in tarjetas], hoy)
    return [_a_out(t, hoy, pagos) for t in tarjetas]


@router.post("", response_model=TarjetaOut, status_code=201, summary="Registra una tarjeta")
def crear(body: TarjetaCrear, db: Session = Depends(get_db),
          usuario: Usuario = Depends(usuario_actual)):
    t = Tarjeta(usuario_id=usuario.id, **body.model_dump())
    db.add(t)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return _out(db, t)


@router.get("/{id}", response_model=TarjetaOut, summary="Detalle de una tarjeta")
def detalle(id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    return _out(db, tarjeta_del_usuario(db, usuario, id))


@router.put("/{id}", response_model=TarjetaOut,
            summary="Edita una tarjeta (solo cambia los campos enviados)")
def editar(id: int, body: TarjetaEditar, db: Session = Depends(get_db),
           usuario: Usuario = Depends(usuario_actual)):
    t = tarjeta_del_usuario(db, usuario, id)
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(t, campo, valor)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return _out(db, t)


@router.delete("/{id}", response_model=TarjetaEliminadaOut,
               summary="Elimina la tarjeta y, en cascada, sus MSI y estados de cuenta")
def eliminar(id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    t = tarjeta_del_usuario(db, usuario, id)
    n_msi = db.scalar(select(func.count()).select_from(PlanMsi).where(PlanMsi.tarjeta_id == t.id))
    db.delete(t)  # ON DELETE CASCADE borra estados, movimientos y planes MSI
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return TarjetaEliminadaOut(id=id, planes_msi_eliminados=n_msi or 0)
