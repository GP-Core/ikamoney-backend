from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.services import fechas
from app.core.database import get_db
from app.core.errores import ApiError, campo_error
from app.models import Categoria, PlanMsi, Tarjeta, Usuario
from app.services.recalculo import recalcular
from app.api.routes.tarjetas import tarjeta_del_usuario
from app.schemas.finanzas import EliminadoOut, MsiCrear, MsiEditar, MsiOut
from app.core.seguridad import usuario_actual

router = APIRouter(prefix="/msi", tags=["MSI"])


# ---------------------------------------------------------------- helpers
def _plan_del_usuario(db: Session, usuario: Usuario, plan_id: int) -> PlanMsi:
    """El dueño del plan se obtiene por su tarjeta (T18 §4.1: no hay usuario_id en plan_msi)."""
    plan = db.scalar(
        select(PlanMsi).join(Tarjeta, PlanMsi.tarjeta_id == Tarjeta.id)
        .where(PlanMsi.id == plan_id, Tarjeta.usuario_id == usuario.id))
    if plan is None:
        raise ApiError(404, "MSI_NO_ENCONTRADO", "La compra a MSI no existe.")
    return plan


def _validar_categoria(db: Session, usuario: Usuario, categoria_id: Optional[int]) -> None:
    if categoria_id is None:
        return
    ok = db.scalar(select(Categoria.id).where(
        Categoria.id == categoria_id,
        or_(Categoria.usuario_id == usuario.id, Categoria.usuario_id.is_(None))))
    if ok is None:
        raise ApiError(404, "CATEGORIA_NO_ENCONTRADA", "La categoría no existe.")


def _tarjeta_para_msi(db: Session, usuario: Usuario, tarjeta_id: int) -> Tarjeta:
    t = tarjeta_del_usuario(db, usuario, tarjeta_id)
    if not t.activa:
        raise ApiError(400, "TARJETA_INACTIVA", "No se puede ligar un MSI a una tarjeta inactiva.")
    return t


def _mensualidad_calculada(monto_original: Decimal, num: int) -> Decimal:
    return fechas.a_centavos(monto_original / num)


def _validar_plan(monto_original: Decimal, num: int, pagadas: int, mensualidad: Decimal,
                  fecha_compra: date) -> None:
    """Reglas que cruzan campos (T18 §4.1)."""
    if pagadas > num:
        raise ApiError(422, "MSI_PAGADAS_EXCEDEN",
                       "Las mensualidades pagadas no pueden ser más que el total.",
                       [campo_error("mensualidades_pagadas", f"Máximo {num}.")])
    if mensualidad <= 0:
        raise ApiError(422, "MONTO_INVALIDO", "El monto debe ser mayor a cero.",
                       [campo_error("monto_mensualidad", "Debe ser mayor a cero.")])
    # Coherencia: mensualidad × meses = monto original, con hasta 1 centavo por mensualidad.
    if abs(mensualidad * num - monto_original) > fechas.CENTAVO * num:
        raise ApiError(
            422, "MSI_MONTOS_INCOHERENTES",
            "La mensualidad por el número de meses debe igualar el monto original "
            "(solo meses sin intereses; tolerancia de 1 centavo por mensualidad).",
            [campo_error("monto_mensualidad", "No cuadra con monto_original y num_mensualidades.")])
    if fecha_compra > fechas.hoy_mx():
        raise ApiError(422, "FECHA_INVALIDA", "La fecha de compra no puede ser futura.",
                       [campo_error("fecha_compra", "No puede ser futura.")])


def _estatus(solicitado: Optional[str], pagadas: int, num: int) -> str:
    """'liquidado' lo decide el servidor (pagadas == total); 'cancelado' lo decide el usuario."""
    if solicitado == "cancelado":
        return "cancelado"
    return "liquidado" if pagadas == num else "activo"


def _a_out(p: PlanMsi) -> MsiOut:
    restantes = p.num_mensualidades - p.mensualidades_pagadas
    return MsiOut(
        id=p.id, tarjeta_id=p.tarjeta_id, categoria_id=p.categoria_id,
        descripcion=p.descripcion, monto_original=p.monto_original,
        num_mensualidades=p.num_mensualidades, mensualidades_pagadas=p.mensualidades_pagadas,
        mensualidades_restantes=restantes, monto_mensualidad=p.monto_mensualidad,
        saldo_pendiente=fechas.a_centavos(restantes * p.monto_mensualidad),
        fecha_compra=p.fecha_compra, estatus=p.estatus, origen=p.origen)


# --------------------------------------------------------------- endpoints
@router.get("", response_model=list[MsiOut],
            summary="Compras a MSI con mensualidades pagadas y restantes")
def listar(tarjeta_id: Optional[int] = Query(None, ge=1, description="Filtra por tarjeta"),
           estatus: Optional[Literal["activo", "liquidado", "cancelado"]] = Query(None),
           db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    consulta = (select(PlanMsi).join(Tarjeta, PlanMsi.tarjeta_id == Tarjeta.id)
                .where(Tarjeta.usuario_id == usuario.id)
                .order_by(PlanMsi.fecha_compra.desc(), PlanMsi.id.desc()))
    if tarjeta_id is not None:
        consulta = consulta.where(PlanMsi.tarjeta_id == tarjeta_id)
    if estatus:
        consulta = consulta.where(PlanMsi.estatus == estatus)
    return [_a_out(p) for p in db.scalars(consulta).all()]


@router.post("", response_model=MsiOut, status_code=201,
             summary="Registra una compra a MSI ligada a una tarjeta")
def crear(body: MsiCrear, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    _tarjeta_para_msi(db, usuario, body.tarjeta_id)
    _validar_categoria(db, usuario, body.categoria_id)
    mensualidad = body.monto_mensualidad or _mensualidad_calculada(body.monto_original,
                                                                    body.num_mensualidades)
    _validar_plan(body.monto_original, body.num_mensualidades, body.mensualidades_pagadas,
                  mensualidad, body.fecha_compra)
    datos = body.model_dump(exclude={"monto_mensualidad"})
    plan = PlanMsi(**datos, monto_mensualidad=mensualidad, origen="manual",
                   estatus=_estatus(None, body.mensualidades_pagadas, body.num_mensualidades))
    db.add(plan)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return _a_out(plan)


@router.get("/{id}", response_model=MsiOut, summary="Detalle de una compra a MSI")
def detalle(id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    return _a_out(_plan_del_usuario(db, usuario, id))


@router.put("/{id}", response_model=MsiOut,
            summary="Edita una compra a MSI (p. ej. mensualidades pagadas)")
def editar(id: int, body: MsiEditar, db: Session = Depends(get_db),
           usuario: Usuario = Depends(usuario_actual)):
    plan = _plan_del_usuario(db, usuario, id)
    datos = body.model_dump(exclude_unset=True)

    if "tarjeta_id" in datos and datos["tarjeta_id"] != plan.tarjeta_id:
        _tarjeta_para_msi(db, usuario, datos["tarjeta_id"])
    if "categoria_id" in datos:
        _validar_categoria(db, usuario, datos["categoria_id"])

    monto = datos.get("monto_original", plan.monto_original)
    num = datos.get("num_mensualidades", plan.num_mensualidades)
    pagadas = datos.get("mensualidades_pagadas", plan.mensualidades_pagadas)
    fecha = datos.get("fecha_compra", plan.fecha_compra)
    if "monto_mensualidad" in datos:
        mensualidad = datos["monto_mensualidad"]
    elif "monto_original" in datos or "num_mensualidades" in datos:
        mensualidad = _mensualidad_calculada(monto, num)  # se recalcula para que siga cuadrando
    else:
        mensualidad = plan.monto_mensualidad
    # La fecha solo se valida si el usuario la cambió (un plan viejo siempre es válido)
    _validar_plan(monto, num, pagadas, mensualidad, fecha if "fecha_compra" in datos else date.min)

    solicitado = datos.pop("estatus", None) or ("cancelado" if plan.estatus == "cancelado" else None)
    for campo, valor in datos.items():
        setattr(plan, campo, valor)
    plan.monto_mensualidad = mensualidad
    plan.estatus = _estatus(solicitado, pagadas, num)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return _a_out(plan)


@router.delete("/{id}", response_model=EliminadoOut, summary="Elimina una compra a MSI")
def eliminar(id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    plan = _plan_del_usuario(db, usuario, id)
    db.delete(plan)  # movimiento.plan_msi_id queda en NULL (ON DELETE SET NULL)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return EliminadoOut(id=id)
