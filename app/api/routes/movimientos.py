import re
from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errores import ApiError, campo_error
from app.core.seguridad import usuario_actual
from app.models import Categoria, Gasto, Ingreso, Usuario
from app.schemas.flujo import (ListaMesOut, MovimientoCrear, MovimientoEditar,
                               MovimientoEliminadoOut, MovimientoMesOut,
                               MovimientoOut, TotalesOut)
from app.services import fechas
from app.services.recalculo import recalcular

router = APIRouter(prefix="/movimientos", tags=["Ingresos y gastos"])
_ID = re.compile(r"^(ingreso|gasto)-(\d+)$")


def _err(status: int, codigo: str, mensaje: str, campo: str | None = None) -> ApiError:
    return ApiError(status, codigo, mensaje, [campo_error(campo, mensaje)] if campo else [])


def _validar(tipo, clase, frecuencia, fecha, fecha_fin, categoria_id) -> None:
    """Reglas que cruzan campos (T18 §5: ingreso y gasto)."""
    if fecha_fin is not None and fecha_fin < fecha:
        raise _err(422, "FECHA_FIN_INVALIDA",
                   "La fecha fin no puede ser menor a la fecha de inicio.", "fecha_fin")
    if tipo == "ingreso":
        if clase is not None or categoria_id is not None:
            raise _err(422, "CAMPO_NO_APLICA", "Un ingreso no lleva categoría ni clase (fijo/variable).",
                       "clase" if clase is not None else "categoria_id")
        return
    if categoria_id is None:
        raise _err(422, "CATEGORIA_REQUERIDA", "El gasto necesita una categoría.", "categoria_id")
    if clase is None:
        raise _err(422, "CLASE_REQUERIDA", "Indica si el gasto es 'fijo' o 'variable'.", "clase")
    if clase == "variable" and frecuencia != "unico":
        raise _err(422, "VARIABLE_DEBE_SER_UNICO",
                   "Un gasto variable debe tener frecuencia 'unico'.", "frecuencia")
    if clase == "fijo" and frecuencia == "unico":
        raise _err(422, "FIJO_NO_PUEDE_SER_UNICO",
                   "Un gasto fijo debe repetirse (semanal, quincenal o mensual).", "frecuencia")


def _categoria_visible(db: Session, usuario: Usuario, categoria_id: int) -> Categoria:
    """Categoría base o propia; la de otro usuario se trata como inexistente (404)."""
    c = db.scalar(select(Categoria).where(
        Categoria.id == categoria_id,
        or_(Categoria.usuario_id == usuario.id, Categoria.usuario_id.is_(None))))
    if c is None:
        raise ApiError(404, "CATEGORIA_NO_ENCONTRADA", "La categoría no existe.")
    return c


def _buscar(db: Session, usuario: Usuario, id_texto: str):
    """Id mal formado, inexistente o de otro usuario => 404 (T17 §3)."""
    m = _ID.match(id_texto)
    if not m:
        raise ApiError(404, "MOVIMIENTO_NO_ENCONTRADO", "El movimiento no existe.")
    tipo, n = m.group(1), int(m.group(2))
    modelo = Ingreso if tipo == "ingreso" else Gasto
    obj = db.scalar(select(modelo).where(modelo.id == n, modelo.usuario_id == usuario.id))
    if obj is None:
        raise ApiError(404, "MOVIMIENTO_NO_ENCONTRADO", "El movimiento no existe.")
    return tipo, obj


def _datos(tipo: str, obj, categoria: Optional[str]) -> dict:
    return dict(id=f"{tipo}-{obj.id}", tipo=tipo, concepto=obj.descripcion, monto=obj.monto,
                frecuencia=obj.frecuencia, fecha=obj.fecha_inicio, fecha_fin=obj.fecha_fin,
                activo=obj.activo, categoria_id=getattr(obj, "categoria_id", None),
                categoria=categoria, clase=obj.tipo if tipo == "gasto" else None)


def _nombres(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {c.id: c.nombre for c in db.scalars(select(Categoria).where(Categoria.id.in_(ids)))}


@router.get("", response_model=ListaMesOut,
            summary="Ingresos y gastos del mes con totales (incluye los recurrentes)")
def listar(mes: Optional[str] = Query(None, pattern=r"^20\d{2}-(0[1-9]|1[0-2])$",
                                      description="AAAA-MM; por defecto, el mes actual"),
           tipo: Optional[Literal["ingreso", "gasto"]] = Query(None),
           categoria_id: Optional[int] = Query(None, ge=1, description="Solo gastos de esa categoría"),
           db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    hoy = fechas.hoy_mx()
    anio, m = (hoy.year, hoy.month) if mes is None else (int(mes[:4]), int(mes[5:7]))
    primero, ultimo = date(anio, m, 1), date(anio, m, monthrange(anio, m)[1])

    def vigentes(modelo):
        return select(modelo).where(
            modelo.usuario_id == usuario.id, modelo.activo.is_(True),
            modelo.fecha_inicio <= ultimo,
            or_(modelo.fecha_fin.is_(None), modelo.fecha_fin >= primero))

    items: list[MovimientoMesOut] = []
    t_ing = t_fijo = t_var = Decimal("0.00")

    if tipo in (None, "ingreso") and categoria_id is None:
        for r in db.scalars(vigentes(Ingreso)):
            for f in fechas.ocurrencias_en_mes(r.frecuencia, r.fecha_inicio, r.fecha_fin, anio, m):
                items.append(MovimientoMesOut(**_datos("ingreso", r, None), fecha_ocurrencia=f))
                t_ing += r.monto

    if tipo in (None, "gasto"):
        consulta = vigentes(Gasto)
        if categoria_id is not None:
            consulta = consulta.where(Gasto.categoria_id == categoria_id)
        gastos = db.scalars(consulta).all()
        nombres = _nombres(db, {g.categoria_id for g in gastos})
        for g in gastos:
            for f in fechas.ocurrencias_en_mes(g.frecuencia, g.fecha_inicio, g.fecha_fin, anio, m):
                items.append(MovimientoMesOut(**_datos("gasto", g, nombres.get(g.categoria_id)),
                                              fecha_ocurrencia=f))
                if g.tipo == "fijo":
                    t_fijo += g.monto
                else:
                    t_var += g.monto

    items.sort(key=lambda x: (x.fecha_ocurrencia, x.id))
    totales = TotalesOut(ingresos=t_ing, gastos=t_fijo + t_var, gastos_fijos=t_fijo,
                         gastos_variables=t_var, balance=t_ing - t_fijo - t_var)
    return ListaMesOut(mes=f"{anio:04d}-{m:02d}", totales=totales, movimientos=items)


@router.post("", response_model=MovimientoOut, status_code=201,
             summary="Registra un ingreso o un gasto (fijo o variable)")
def crear(body: MovimientoCrear, db: Session = Depends(get_db),
          usuario: Usuario = Depends(usuario_actual)):
    _validar(body.tipo, body.clase, body.frecuencia, body.fecha, body.fecha_fin, body.categoria_id)
    nombre_cat = None
    if body.tipo == "ingreso":
        obj = Ingreso(usuario_id=usuario.id, descripcion=body.concepto, monto=body.monto,
                      frecuencia=body.frecuencia, fecha_inicio=body.fecha,
                      fecha_fin=body.fecha_fin, activo=body.activo)
    else:
        cat = _categoria_visible(db, usuario, body.categoria_id)
        nombre_cat = cat.nombre
        obj = Gasto(usuario_id=usuario.id, categoria_id=cat.id, descripcion=body.concepto,
                    tipo=body.clase, monto=body.monto, frecuencia=body.frecuencia,
                    fecha_inicio=body.fecha, fecha_fin=body.fecha_fin, activo=body.activo)
    db.add(obj)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return MovimientoOut(**_datos(body.tipo, obj, nombre_cat))


@router.put("/{id}", response_model=MovimientoOut,
            summary="Edita un movimiento (solo cambia los campos enviados)")
def editar(id: str, body: MovimientoEditar, db: Session = Depends(get_db),
           usuario: Usuario = Depends(usuario_actual)):
    tipo, obj = _buscar(db, usuario, id)
    datos = body.model_dump(exclude_unset=True)
    es_gasto = tipo == "gasto"

    # Estado final tras el cambio: se valida completo antes de tocar nada
    final = dict(frecuencia=obj.frecuencia, fecha=obj.fecha_inicio, fecha_fin=obj.fecha_fin,
                 categoria_id=obj.categoria_id if es_gasto else None,
                 clase=obj.tipo if es_gasto else None)
    final.update({k: v for k, v in datos.items() if k in final})
    _validar(tipo, final["clase"], final["frecuencia"], final["fecha"], final["fecha_fin"],
             final["categoria_id"])
    if es_gasto and "categoria_id" in datos:
        _categoria_visible(db, usuario, datos["categoria_id"])

    if "concepto" in datos:
        obj.descripcion = datos["concepto"]
    if "fecha" in datos:
        obj.fecha_inicio = datos["fecha"]
    for campo in ("monto", "frecuencia", "fecha_fin", "activo"):
        if campo in datos:
            setattr(obj, campo, datos[campo])
    if es_gasto:
        if "clase" in datos:
            obj.tipo = datos["clase"]
        if "categoria_id" in datos:
            obj.categoria_id = datos["categoria_id"]
    db.flush()
    recalcular(db, usuario)
    db.commit()
    nombre = db.get(Categoria, obj.categoria_id).nombre if es_gasto else None
    return MovimientoOut(**_datos(tipo, obj, nombre))


@router.delete("/{id}", response_model=MovimientoEliminadoOut, summary="Elimina un movimiento")
def eliminar(id: str, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    _, obj = _buscar(db, usuario, id)
    db.delete(obj)
    db.flush()
    recalcular(db, usuario)
    db.commit()
    return MovimientoEliminadoOut(id=id)
