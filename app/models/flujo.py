"""`gasto` cubre solo lo que NO viene de un estado de cuenta (renta, servicios, efectivo, débito).
El gasto de tarjeta entra por los movimientos del estado de cuenta, para no contarlo dos veces.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Date, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.comunes import Dinero, Id, Marcas, fk

FRECUENCIAS = ("unico", "semanal", "quincenal", "mensual", "anual")


class Ingreso(Base, Marcas):
    __tablename__ = "ingreso"
    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_ingreso_monto"),
        CheckConstraint("fecha_fin IS NULL OR fecha_fin >= fecha_inicio", name="ck_ingreso_fechas"),
    )
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = fk("usuario.id")
    descripcion: Mapped[str] = mapped_column(String(120), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    frecuencia: Mapped[str] = mapped_column(Enum(*FRECUENCIAS, name="ingreso_frecuencia"), nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Gasto(Base, Marcas):
    __tablename__ = "gasto"
    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_gasto_monto"),
        CheckConstraint("fecha_fin IS NULL OR fecha_fin >= fecha_inicio", name="ck_gasto_fechas"),
        CheckConstraint("tipo <> 'variable' OR frecuencia = 'unico'", name="ck_gasto_variable"),
        CheckConstraint("tipo <> 'fijo' OR frecuencia <> 'unico'", name="ck_gasto_fijo"),
    )
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = fk("usuario.id")
    # RESTRICT: no se puede borrar una categoría que tenga gastos (T18 §3)
    categoria_id: Mapped[int] = fk("categoria.id", "RESTRICT")
    descripcion: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(Enum("fijo", "variable", name="gasto_tipo"), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    frecuencia: Mapped[str] = mapped_column(Enum(*FRECUENCIAS, name="gasto_frecuencia"), nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
