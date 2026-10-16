"""Esquemas de /movimientos (ingresos y gastos) y /categorias (T17 §4.2)."""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.finanzas import Dinero, _Edicion, _Entrada

Frecuencia = Literal["unico", "semanal", "quincenal", "mensual"]  # T17 §4.2
TipoMov = Literal["ingreso", "gasto"]
Clase = Literal["fijo", "variable"]


class MovimientoCrear(_Entrada):
    tipo: TipoMov
    concepto: str = Field(min_length=1, max_length=120)
    monto: Dinero = Field(gt=0)
    frecuencia: Frecuencia = "unico"
    fecha: date                                  # en 'unico' es la fecha del movimiento
    fecha_fin: Optional[date] = None
    categoria_id: Optional[int] = Field(default=None, ge=1)   # obligatoria si es gasto
    clase: Optional[Clase] = None                              # obligatoria si es gasto
    activo: bool = True


class MovimientoEditar(_Edicion):
    """PUT parcial. El tipo (ingreso/gasto) no se puede cambiar."""
    NO_NULOS = ("concepto", "monto", "frecuencia", "fecha", "activo")
    concepto: Optional[str] = Field(default=None, min_length=1, max_length=120)
    monto: Optional[Dinero] = Field(default=None, gt=0)
    frecuencia: Optional[Frecuencia] = None
    fecha: Optional[date] = None
    fecha_fin: Optional[date] = None
    categoria_id: Optional[int] = Field(default=None, ge=1)
    clase: Optional[Clase] = None
    activo: Optional[bool] = None


class MovimientoOut(BaseModel):
    id: str                                      # "ingreso-5" / "gasto-12"
    tipo: TipoMov
    concepto: str
    monto: Dinero
    frecuencia: str
    fecha: date                                  # fecha_inicio
    fecha_fin: Optional[date]
    activo: bool
    categoria_id: Optional[int]
    categoria: Optional[str]
    clase: Optional[str]


class MovimientoMesOut(MovimientoOut):
    fecha_ocurrencia: date                       # día exacto dentro del mes consultado


class TotalesOut(BaseModel):
    ingresos: Dinero
    gastos: Dinero
    gastos_fijos: Dinero
    gastos_variables: Dinero
    balance: Dinero


class ListaMesOut(BaseModel):
    mes: str
    totales: TotalesOut
    movimientos: list[MovimientoMesOut]


class MovimientoEliminadoOut(BaseModel):
    id: str
    eliminado: bool = True


class CategoriaCrear(_Entrada):
    nombre: str = Field(min_length=1, max_length=60)


class CategoriaOut(BaseModel):
    id: int
    nombre: str
    base: bool                                   # True = categoría del sistema
