"""Ingresos y gastos (T17 §4.2). Un solo recurso, dos tablas (T18): `ingreso` y `gasto`.

El id público lleva prefijo: "ingreso-5" o "gasto-12".
"""
import re
from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errores import ApiError, campo_error
from app.models import Categoria, Gasto, Ingreso, Usuario
from app.schemas.movimiento import (ListaMesOut, MovimientoCrear, MovimientoEditar,
                                    MovimientoEliminadoOut, MovimientoMesOut,
                                    MovimientoOut, TotalesOut)
from app.services import categorias, fechas
from app.services.comunes import confirmar

_ID = re.compile(r"^(ingreso|gasto)-(\d+)$")


# ----------------------------------------------------------- reglas puras
def _error(status: int, codigo: str, mensaje: str, campo: str | None = None) -> ApiError:
    return ApiError(status, codigo, mensaje, [campo_error(campo, mensaje)] if campo else [])


def validar_movimiento(tipo, clase, frecuencia, fecha, fecha_fin, categoria_id) -> None:
    """Reglas que cruzan campos (T18 §5: ingreso y gasto)."""
    if fecha_fin is not None and fecha_fin < fecha:
        raise _error(422, "FECHA_FIN_INVALIDA",
                     "La fecha fin no puede ser menor a la fecha de inicio.", "fecha_fin")
    if tipo == "ingreso":
        if clase is not None or categoria_id is not None:
            raise _error(422, "CAMPO_NO_APLICA",
                         "Un ingreso no lleva categoría ni clase (fijo/variable).",
                         "clase" if clase is not None else "categoria_id")
        return
    if categoria_id is None:
        raise _error(422, "CATEGORIA_REQUERIDA", "El gasto necesita una categoría.", "categoria_id")
    if clase is None:
        raise _error(422, "CLASE_REQUERIDA", "Indica si el gasto es 'fijo' o 'variable'.", "clase")
    if clase == "variable" and frecuencia != "unico":
        raise _error(422, "VARIABLE_DEBE_SER_UNICO",
                     "Un gasto variable debe tener frecuencia 'unico'.", "frecuencia")
    if clase == "fijo" and frecuencia == "unico":
        raise _error(422, "FIJO_NO_PUEDE_SER_UNICO",
                     "Un gasto fijo debe repetirse (semanal, quincenal o mensual).", "frecuencia")


# --------------------------------------------------------------- acceso
def obtener(db: Session, usuario: Usuario, id_texto: str):
    """Devuelve (tipo, registro). Id mal formado, inexistente o ajeno => 404 (T17 §3)."""
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


def a_out(tipo: str, obj, categoria: Optional[str] = None) -> MovimientoOut:
    return MovimientoOut(**_datos(tipo, obj, categoria))


def _nombres_categorias(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {c.id: c.nombre for c in db.scalars(select(Categoria).where(Categoria.id.in_(ids)))}


# ------------------------------------------------------------- consulta
def _vigentes(modelo, usuario: Usuario, primero: date, ultimo: date):
    return select(modelo).where(
        modelo.usuario_id == usuario.id, modelo.activo.is_(True),
        modelo.fecha_inicio <= ultimo,
        or_(modelo.fecha_fin.is_(None), modelo.fecha_fin >= primero))


def listar_mes(db: Session, usuario: Usuario, mes: Optional[str] = None,
               tipo: Optional[str] = None, categoria_id: Optional[int] = None) -> ListaMesOut:
    """Ingresos y gastos del mes (AAAA-MM; por defecto el actual), con totales y recurrentes."""
    hoy = fechas.hoy_mx()
    anio, m = (hoy.year, hoy.month) if mes is None else (int(mes[:4]), int(mes[5:7]))
    primero, ultimo = date(anio, m, 1), date(anio, m, monthrange(anio, m)[1])

    items: list[MovimientoMesOut] = []
    t_ing = t_fijo = t_var = Decimal("0.00")

    if tipo in (None, "ingreso") and categoria_id is None:
        for r in db.scalars(_vigentes(Ingreso, usuario, primero, ultimo)):
            for f in fechas.ocurrencias_en_mes(r.frecuencia, r.fecha_inicio, r.fecha_fin, anio, m):
                items.append(MovimientoMesOut(**_datos("ingreso", r, None), fecha_ocurrencia=f))
                t_ing += r.monto

    if tipo in (None, "gasto"):
        consulta = _vigentes(Gasto, usuario, primero, ultimo)
        if categoria_id is not None:
            consulta = consulta.where(Gasto.categoria_id == categoria_id)
        gastos = db.scalars(consulta).all()
        nombres = _nombres_categorias(db, {g.categoria_id for g in gastos})
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


# ----------------------------------------------------------- escritura
def crear(db: Session, usuario: Usuario, datos: MovimientoCrear) -> MovimientoOut:
    validar_movimiento(datos.tipo, datos.clase, datos.frecuencia, datos.fecha,
                       datos.fecha_fin, datos.categoria_id)
    nombre_categoria = None
    if datos.tipo == "ingreso":
        obj = Ingreso(usuario_id=usuario.id, descripcion=datos.concepto, monto=datos.monto,
                      frecuencia=datos.frecuencia, fecha_inicio=datos.fecha,
                      fecha_fin=datos.fecha_fin, activo=datos.activo)
    else:
        categoria = categorias.obtener_visible(db, usuario, datos.categoria_id)
        nombre_categoria = categoria.nombre
        obj = Gasto(usuario_id=usuario.id, categoria_id=categoria.id, descripcion=datos.concepto,
                    tipo=datos.clase, monto=datos.monto, frecuencia=datos.frecuencia,
                    fecha_inicio=datos.fecha, fecha_fin=datos.fecha_fin, activo=datos.activo)
    db.add(obj)
    confirmar(db, usuario)
    return a_out(datos.tipo, obj, nombre_categoria)


def editar(db: Session, usuario: Usuario, id_texto: str, datos: MovimientoEditar) -> MovimientoOut:
    tipo, obj = obtener(db, usuario, id_texto)
    cambios = datos.model_dump(exclude_unset=True)
    es_gasto = tipo == "gasto"

    # Estado final tras el cambio: se valida completo antes de tocar nada
    final = dict(frecuencia=obj.frecuencia, fecha=obj.fecha_inicio, fecha_fin=obj.fecha_fin,
                 categoria_id=obj.categoria_id if es_gasto else None,
                 clase=obj.tipo if es_gasto else None)
    final.update({k: v for k, v in cambios.items() if k in final})
    validar_movimiento(tipo, final["clase"], final["frecuencia"], final["fecha"],
                       final["fecha_fin"], final["categoria_id"])
    if es_gasto and "categoria_id" in cambios:
        categorias.obtener_visible(db, usuario, cambios["categoria_id"])

    if "concepto" in cambios:
        obj.descripcion = cambios["concepto"]
    if "fecha" in cambios:
        obj.fecha_inicio = cambios["fecha"]
    for campo in ("monto", "frecuencia", "fecha_fin", "activo"):
        if campo in cambios:
            setattr(obj, campo, cambios[campo])
    if es_gasto:
        if "clase" in cambios:
            obj.tipo = cambios["clase"]
        if "categoria_id" in cambios:
            obj.categoria_id = cambios["categoria_id"]
    confirmar(db, usuario)
    nombre = db.get(Categoria, obj.categoria_id).nombre if es_gasto else None
    return a_out(tipo, obj, nombre)


def eliminar(db: Session, usuario: Usuario, id_texto: str) -> MovimientoEliminadoOut:
    _, obj = obtener(db, usuario, id_texto)
    db.delete(obj)
    confirmar(db, usuario)
    return MovimientoEliminadoOut(id=id_texto)
