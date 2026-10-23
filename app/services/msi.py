"""Compras a meses sin intereses (MSI), ligadas a una tarjeta (T17 §4.3, T18 §4.1)."""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import ApiError, campo_error
from app.models import PlanMsi, Tarjeta, Usuario
from app.schemas.base import EliminadoOut
from app.schemas.msi import MsiCrear, MsiEditar, MsiOut
from app.services import categorias, fechas, tarjetas
from app.services.comunes import confirmar


# ----------------------------------------------------------- reglas puras
def mensualidad_calculada(monto_original: Decimal, num: int) -> Decimal:
    return fechas.a_centavos(monto_original / num)


def validar_plan(monto_original: Decimal, num: int, pagadas: int, mensualidad: Decimal,
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


def calcular_estatus(solicitado: Optional[str], pagadas: int, num: int) -> str:
    """'liquidado' lo decide el servidor (pagadas == total); 'cancelado' lo decide el usuario."""
    if solicitado == "cancelado":
        return "cancelado"
    return "liquidado" if pagadas == num else "activo"


# --------------------------------------------------------------- acceso
def obtener(db: Session, usuario: Usuario, plan_id: int) -> PlanMsi:
    """El dueño del plan se obtiene por su tarjeta (T18 §4.1: no hay usuario_id en plan_msi)."""
    plan = db.scalar(
        select(PlanMsi).join(Tarjeta, PlanMsi.tarjeta_id == Tarjeta.id)
        .where(PlanMsi.id == plan_id, Tarjeta.usuario_id == usuario.id))
    if plan is None:
        raise ApiError(404, "MSI_NO_ENCONTRADO", "La compra a MSI no existe.")
    return plan


def _tarjeta_para_msi(db: Session, usuario: Usuario, tarjeta_id: int) -> Tarjeta:
    t = tarjetas.obtener(db, usuario, tarjeta_id)
    if not t.activa:
        raise ApiError(400, "TARJETA_INACTIVA", "No se puede ligar un MSI a una tarjeta inactiva.")
    return t


def _validar_categoria(db: Session, usuario: Usuario, categoria_id: Optional[int]) -> None:
    if categoria_id is not None:
        categorias.obtener_visible(db, usuario, categoria_id)


def a_out(p: PlanMsi) -> MsiOut:
    """Las mensualidades restantes y el saldo pendiente se calculan, no se guardan."""
    restantes = p.num_mensualidades - p.mensualidades_pagadas
    return MsiOut(
        id=p.id, tarjeta_id=p.tarjeta_id, categoria_id=p.categoria_id,
        descripcion=p.descripcion, monto_original=p.monto_original,
        num_mensualidades=p.num_mensualidades, mensualidades_pagadas=p.mensualidades_pagadas,
        mensualidades_restantes=restantes, monto_mensualidad=p.monto_mensualidad,
        saldo_pendiente=fechas.a_centavos(restantes * p.monto_mensualidad),
        fecha_compra=p.fecha_compra, estatus=p.estatus, origen=p.origen)


# ----------------------------------------------------------- operaciones
def listar(db: Session, usuario: Usuario, tarjeta_id: Optional[int] = None,
           estatus: Optional[str] = None) -> list[MsiOut]:
    consulta = (select(PlanMsi).join(Tarjeta, PlanMsi.tarjeta_id == Tarjeta.id)
                .where(Tarjeta.usuario_id == usuario.id)
                .order_by(PlanMsi.fecha_compra.desc(), PlanMsi.id.desc()))
    if tarjeta_id is not None:
        consulta = consulta.where(PlanMsi.tarjeta_id == tarjeta_id)
    if estatus:
        consulta = consulta.where(PlanMsi.estatus == estatus)
    return [a_out(p) for p in db.scalars(consulta).all()]


def crear(db: Session, usuario: Usuario, datos: MsiCrear) -> MsiOut:
    _tarjeta_para_msi(db, usuario, datos.tarjeta_id)
    _validar_categoria(db, usuario, datos.categoria_id)
    mensualidad = datos.monto_mensualidad or mensualidad_calculada(
        datos.monto_original, datos.num_mensualidades)
    validar_plan(datos.monto_original, datos.num_mensualidades, datos.mensualidades_pagadas,
                 mensualidad, datos.fecha_compra)
    plan = PlanMsi(**datos.model_dump(exclude={"monto_mensualidad"}),
                   monto_mensualidad=mensualidad, origen="manual",
                   estatus=calcular_estatus(None, datos.mensualidades_pagadas,
                                            datos.num_mensualidades))
    db.add(plan)
    confirmar(db, usuario)
    return a_out(plan)


def detalle(db: Session, usuario: Usuario, plan_id: int) -> MsiOut:
    return a_out(obtener(db, usuario, plan_id))


def editar(db: Session, usuario: Usuario, plan_id: int, datos: MsiEditar) -> MsiOut:
    plan = obtener(db, usuario, plan_id)
    cambios = datos.model_dump(exclude_unset=True)

    if "tarjeta_id" in cambios and cambios["tarjeta_id"] != plan.tarjeta_id:
        _tarjeta_para_msi(db, usuario, cambios["tarjeta_id"])
    if "categoria_id" in cambios:
        _validar_categoria(db, usuario, cambios["categoria_id"])

    monto = cambios.get("monto_original", plan.monto_original)
    num = cambios.get("num_mensualidades", plan.num_mensualidades)
    pagadas = cambios.get("mensualidades_pagadas", plan.mensualidades_pagadas)
    fecha = cambios.get("fecha_compra", plan.fecha_compra)
    if "monto_mensualidad" in cambios:
        mensualidad = cambios["monto_mensualidad"]
    elif "monto_original" in cambios or "num_mensualidades" in cambios:
        mensualidad = mensualidad_calculada(monto, num)  # se recalcula para que siga cuadrando
    else:
        mensualidad = plan.monto_mensualidad
    # La fecha solo se valida si el usuario la cambió (un plan viejo siempre es válido)
    validar_plan(monto, num, pagadas, mensualidad,
                 fecha if "fecha_compra" in cambios else date.min)

    solicitado = cambios.pop("estatus", None) or ("cancelado" if plan.estatus == "cancelado" else None)
    for campo, valor in cambios.items():
        setattr(plan, campo, valor)
    plan.monto_mensualidad = mensualidad
    plan.estatus = calcular_estatus(solicitado, pagadas, num)
    confirmar(db, usuario)
    return a_out(plan)


def eliminar(db: Session, usuario: Usuario, plan_id: int) -> EliminadoOut:
    plan = obtener(db, usuario, plan_id)
    db.delete(plan)  # movimiento.plan_msi_id queda en NULL (ON DELETE SET NULL)
    confirmar(db, usuario)
    return EliminadoOut(id=plan_id)
