"""Alertas del usuario (T47) y su configuración (T49).

`clave_activa` vale 'REGLA|referencia' mientras la alerta está activa y NULL al resolverse. Con el
UNIQUE (usuario_id, clave_activa) la base impide dos alertas activas iguales aunque dos peticiones
lleguen a la vez; las filas resueltas se conservan como historial.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (Boolean, DateTime, Enum, Index, SmallInteger, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.comunes import Id, Marcas, TinyUns, fk


class Alerta(Base, Marcas):
    __tablename__ = "alerta"
    __table_args__ = (
        UniqueConstraint("usuario_id", "clave_activa", name="uq_alerta_usuario_clave_activa"),
        Index("ix_alerta_usuario_disparada", "usuario_id", "disparada_en"),
    )
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = fk("usuario.id")
    regla: Mapped[str] = mapped_column(String(10), nullable=False)          # AL-01 a AL-04
    referencia: Mapped[str] = mapped_column(String(60), nullable=False)     # 'proyeccion', 'tarjeta:7'...
    severidad: Mapped[str] = mapped_column(
        Enum("atencion", "critica", name="alerta_severidad"), nullable=False)
    titulo: Mapped[str] = mapped_column(String(120), nullable=False)
    mensaje: Mapped[str] = mapped_column(String(300), nullable=False)       # sin saldos (IC-07)
    accion: Mapped[str] = mapped_column(String(200), nullable=False)
    estado: Mapped[str] = mapped_column(
        Enum("activa", "resuelta", name="alerta_estado"), nullable=False, default="activa")
    clave_activa: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    disparada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    leida_en: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resuelta_en: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notificada_en: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AlertaConfiguracion(Base, Marcas):
    __tablename__ = "alerta_configuracion"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = fk("usuario.id")
    umbral_utilizacion: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=70)
    dias_anticipacion: Mapped[int] = mapped_column(TinyUns, nullable=False, default=3)
    canal_correo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    canal_push: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("usuario_id", name="uq_alerta_configuracion_usuario"),)
