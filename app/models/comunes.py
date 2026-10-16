"""Tipos y utilidades comunes a los modelos (convenciones de T18 §2)."""
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, Numeric, SmallInteger, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

# BIGINT UNSIGNED en MySQL; INTEGER en SQLite (para que autoincremente en pruebas)
Id = Integer().with_variant(mysql.BIGINT(unsigned=True), "mysql")
TinyUns = SmallInteger().with_variant(mysql.TINYINT(unsigned=True), "mysql")
SmallUns = SmallInteger().with_variant(mysql.SMALLINT(unsigned=True), "mysql")
Dinero = Numeric(12, 2)
Tasa = Numeric(5, 2)


class Marcas:
    """creado_en y actualizado_en: obligatorios y automáticos en todas las tablas."""
    creado_en: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.current_timestamp(), nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(), nullable=False)


def fk(destino: str, borrado: str = "CASCADE", nullable: bool = False):
    return mapped_column(Id, ForeignKey(destino, ondelete=borrado), nullable=nullable)
