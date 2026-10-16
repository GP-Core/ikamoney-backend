from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import fechas
from app.core.database import get_db
from app.core.errores import ApiError
from app.models import Deuda, Usuario
from app.services.recalculo import recalcular
from app.schemas.finanzas import DeudaCrear, DeudaEditar, DeudaOut, EliminadoOut
from app.core.seguridad import usuario_actual

router = APIRouter(prefix="/deudas", tags=["Deudas"])


def _deuda_del_usuario(db: Session, usuario: Usuario, deuda_id: int) -> Deuda:
    d = db.scalar(select(Deuda).where(Deuda.id == deuda_id, Deuda.usuario_id == usuario.id))
    if d is None:
        raise ApiError(404, "DEUDA_NO_ENCONTRADA", "La deuda no existe.")
    return d


def _estatus(saldo) -> str:
    return "liquidada" if saldo == 0 else "activa"


def _a_out(d: Deuda) -> DeudaOut:
    proxima = None
    if d.estatus == "activa" and d.dia_pago:
        proxima = fechas.proxima_fecha(d.dia_pago, fechas.hoy_mx())
    return DeudaOut(
        id=d.id, nombre=d.nombre, acreedor=d.acreedor, tipo=d.tipo,
        monto_original=d.monto_original, saldo_actual=d.saldo_actual, tasa_anual=d.tasa_anual,
        pago_mensual=d.pago_mensual, dia_pago=d.dia_pago, fecha_inicio=d.fecha_inicio,
        estatus=d.estatus, proxima_fecha_pago=proxima)


@router.get("", response_model=list[DeudaOut], summary="Préstamos y créditos con saldo y próximo pago")
def listar(estatus: Optional[Literal["activa", "liquidada"]] = Query(None),
           db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    consulta = select(Deuda).where(Deuda.usuario_id == usuario.id).order_by(Deuda.id)
    if estatus:
        consulta = consulta.where(Deuda.estatus == estatus)
    return [_a_out(d) for d in db.scalars(consulta).all()]


@router.post("", response_model=DeudaOut, status_code=201, summary="Registra otra deuda")
def crear(body: DeudaCrear, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    d = Deuda(usuario_id=usuario.id, estatus=_estatus(body.saldo_actual), **body.model_dump())
    db.add(d)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return _a_out(d)


@router.get("/{id}", response_model=DeudaOut, summary="Detalle de una deuda")
def detalle(id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    return _a_out(_deuda_del_usuario(db, usuario, id))


@router.put("/{id}", response_model=DeudaOut, summary="Edita una deuda (solo cambia los campos enviados)")
def editar(id: int, body: DeudaEditar, db: Session = Depends(get_db),
           usuario: Usuario = Depends(usuario_actual)):
    d = _deuda_del_usuario(db, usuario, id)
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(d, campo, valor)
    d.estatus = _estatus(d.saldo_actual)  # liquidar = dejar el saldo en 0; subirlo la reactiva
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return _a_out(d)


@router.delete("/{id}", response_model=EliminadoOut, summary="Elimina una deuda")
def eliminar(id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    d = _deuda_del_usuario(db, usuario, id)
    db.delete(d)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return EliminadoOut(id=id)
