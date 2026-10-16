"""Deudas (préstamos y créditos que no son tarjeta) (T17 §4.3)."""
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import ApiError
from app.models import Deuda, Usuario
from app.schemas.base import EliminadoOut
from app.schemas.deuda import DeudaCrear, DeudaEditar, DeudaOut
from app.services import fechas
from app.services.comunes import confirmar, obtener_del_usuario


def obtener(db: Session, usuario: Usuario, deuda_id: int) -> Deuda:
    return obtener_del_usuario(db, Deuda, deuda_id, usuario,
                               ApiError(404, "DEUDA_NO_ENCONTRADA", "La deuda no existe."))


def estatus_por_saldo(saldo: Decimal) -> str:
    """Saldo 0 => 'liquidada'; subirlo la reactiva."""
    return "liquidada" if saldo == 0 else "activa"


def a_out(d: Deuda) -> DeudaOut:
    proxima = None
    if d.estatus == "activa" and d.dia_pago:
        proxima = fechas.proxima_fecha(d.dia_pago, fechas.hoy_mx())
    return DeudaOut(
        id=d.id, nombre=d.nombre, acreedor=d.acreedor, tipo=d.tipo,
        monto_original=d.monto_original, saldo_actual=d.saldo_actual, tasa_anual=d.tasa_anual,
        pago_mensual=d.pago_mensual, dia_pago=d.dia_pago, fecha_inicio=d.fecha_inicio,
        estatus=d.estatus, proxima_fecha_pago=proxima)


def listar(db: Session, usuario: Usuario, estatus: Optional[str] = None) -> list[DeudaOut]:
    consulta = select(Deuda).where(Deuda.usuario_id == usuario.id).order_by(Deuda.id)
    if estatus:
        consulta = consulta.where(Deuda.estatus == estatus)
    return [a_out(d) for d in db.scalars(consulta).all()]


def crear(db: Session, usuario: Usuario, datos: DeudaCrear) -> DeudaOut:
    d = Deuda(usuario_id=usuario.id, estatus=estatus_por_saldo(datos.saldo_actual),
              **datos.model_dump())
    db.add(d)
    confirmar(db, usuario)
    return a_out(d)


def detalle(db: Session, usuario: Usuario, deuda_id: int) -> DeudaOut:
    return a_out(obtener(db, usuario, deuda_id))


def editar(db: Session, usuario: Usuario, deuda_id: int, datos: DeudaEditar) -> DeudaOut:
    d = obtener(db, usuario, deuda_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(d, campo, valor)
    d.estatus = estatus_por_saldo(d.saldo_actual)
    confirmar(db, usuario)
    return a_out(d)


def eliminar(db: Session, usuario: Usuario, deuda_id: int) -> EliminadoOut:
    d = obtener(db, usuario, deuda_id)
    db.delete(d)
    confirmar(db, usuario)
    return EliminadoOut(id=deuda_id)
