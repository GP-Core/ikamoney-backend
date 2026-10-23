from typing import Optional

from sqlalchemy import CHAR, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.comunes import Id, Marcas, fk


class Usuario(Base, Marcas):
    __tablename__ = "usuario"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    correo: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    contrasena_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    moneda: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="MXN")


class Categoria(Base, Marcas):
    __tablename__ = "categoria"
    __table_args__ = (UniqueConstraint("usuario_id", "nombre", name="uq_categoria_usuario_nombre"),)
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    usuario_id: Mapped[Optional[int]] = fk("usuario.id", nullable=True)  # NULL = base del sistema
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
