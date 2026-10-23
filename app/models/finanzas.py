from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (CHAR, TIMESTAMP, Boolean, CheckConstraint, Date, Enum,
                        Numeric, String, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.comunes import Dinero, Id, Marcas, SmallUns, Tasa, TinyUns, fk


class Tarjeta(Base, Marcas):
    __tablename__ = "tarjeta"
    __table_args__ = (
        CheckConstraint("limite_credito >= 0", name="ck_tarjeta_limite"),
        CheckConstraint("saldo_actual >= 0", name="ck_tarjeta_saldo"),
        CheckConstraint("dia_corte BETWEEN 1 AND 31", name="ck_tarjeta_dia_corte"),
        CheckConstraint("dia_pago BETWEEN 1 AND 31", name="ck_tarjeta_dia_pago"),
        CheckConstraint("tasa_anual IS NULL OR (tasa_anual >= 0 AND tasa_anual <= 999.99)",
                        name="ck_tarjeta_tasa"),
    )
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = fk("usuario.id")
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    banco: Mapped[str] = mapped_column(String(60), nullable=False)
    ultimos_4: Mapped[Optional[str]] = mapped_column(CHAR(4), nullable=True)
    limite_credito: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    saldo_actual: Mapped[Decimal] = mapped_column(Dinero, nullable=False, default=Decimal("0.00"))
    dia_corte: Mapped[int] = mapped_column(TinyUns, nullable=False)
    dia_pago: Mapped[int] = mapped_column(TinyUns, nullable=False)
    tasa_anual: Mapped[Optional[Decimal]] = mapped_column(Tasa, nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EstadoCuenta(Base, Marcas):
    __tablename__ = "estado_cuenta"
    __table_args__ = (
        UniqueConstraint("tarjeta_id", "fecha_corte", name="uq_estado_tarjeta_corte"),
        CheckConstraint("fecha_corte >= periodo_inicio", name="ck_estado_periodo"),
        CheckConstraint("fecha_limite_pago > fecha_corte", name="ck_estado_limite"),
    )
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    tarjeta_id: Mapped[int] = fk("tarjeta.id")
    periodo_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_corte: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_limite_pago: Mapped[date] = mapped_column(Date, nullable=False)
    saldo_al_corte: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    pago_minimo: Mapped[Optional[Decimal]] = mapped_column(Dinero, nullable=True)
    pago_no_intereses: Mapped[Optional[Decimal]] = mapped_column(Dinero, nullable=True)
    archivo_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    estatus: Mapped[str] = mapped_column(
        Enum("procesando", "extraido", "revisado", "error", name="estado_estatus"),
        nullable=False, default="procesando")


class PlanMsi(Base, Marcas):
    __tablename__ = "plan_msi"
    __table_args__ = (
        CheckConstraint("monto_original > 0", name="ck_msi_monto"),
        CheckConstraint("num_mensualidades >= 2", name="ck_msi_num"),
        CheckConstraint("mensualidades_pagadas >= 0 AND mensualidades_pagadas <= num_mensualidades",
                        name="ck_msi_pagadas"),
        CheckConstraint("monto_mensualidad > 0", name="ck_msi_mensualidad"),
    )
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    tarjeta_id: Mapped[int] = fk("tarjeta.id")
    categoria_id: Mapped[Optional[int]] = fk("categoria.id", "SET NULL", nullable=True)
    descripcion: Mapped[str] = mapped_column(String(120), nullable=False)
    monto_original: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    num_mensualidades: Mapped[int] = mapped_column(SmallUns, nullable=False)
    mensualidades_pagadas: Mapped[int] = mapped_column(SmallUns, nullable=False, default=0)
    monto_mensualidad: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    fecha_compra: Mapped[date] = mapped_column(Date, nullable=False)
    estatus: Mapped[str] = mapped_column(
        Enum("activo", "liquidado", "cancelado", name="msi_estatus"),
        nullable=False, default="activo")
    origen: Mapped[str] = mapped_column(
        Enum("extraido", "manual", name="msi_origen"), nullable=False)


class Movimiento(Base, Marcas):
    __tablename__ = "movimiento"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    estado_cuenta_id: Mapped[int] = fk("estado_cuenta.id")
    origen: Mapped[str] = mapped_column(Enum("extraido", "manual", name="mov_origen"), nullable=False)
    estado_revision: Mapped[str] = mapped_column(
        Enum("pendiente", "confirmado", "corregido", "descartado", name="mov_revision"),
        nullable=False, default="pendiente")
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    descripcion: Mapped[str] = mapped_column(String(255), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    tipo: Mapped[str] = mapped_column(
        Enum("cargo", "pago", "interes", "comision", "mensualidad_msi", name="mov_tipo"),
        nullable=False)
    categoria_id: Mapped[Optional[int]] = fk("categoria.id", "SET NULL", nullable=True)
    plan_msi_id: Mapped[Optional[int]] = fk("plan_msi.id", "SET NULL", nullable=True)
    fecha_extraida: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    descripcion_extraida: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    monto_extraido: Mapped[Optional[Decimal]] = mapped_column(Dinero, nullable=True)
    tipo_extraido: Mapped[Optional[str]] = mapped_column(
        Enum("cargo", "pago", "interes", "comision", "mensualidad_msi", name="mov_tipo_ext"),
        nullable=True)
    confianza: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2), nullable=True)
    corregido_en: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)


class Deuda(Base, Marcas):
    __tablename__ = "deuda"
    __table_args__ = (
        CheckConstraint("monto_original > 0", name="ck_deuda_monto"),
        CheckConstraint("saldo_actual >= 0", name="ck_deuda_saldo"),
    )
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = fk("usuario.id")
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    acreedor: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tipo: Mapped[str] = mapped_column(
        Enum("prestamo_personal", "credito_auto", "credito_hipotecario", "familiar_amigo",
             "otro", name="deuda_tipo"), nullable=False)
    monto_original: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    saldo_actual: Mapped[Decimal] = mapped_column(Dinero, nullable=False)
    tasa_anual: Mapped[Optional[Decimal]] = mapped_column(Tasa, nullable=True)
    pago_mensual: Mapped[Optional[Decimal]] = mapped_column(Dinero, nullable=True)
    dia_pago: Mapped[Optional[int]] = mapped_column(TinyUns, nullable=True)
    fecha_inicio: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    estatus: Mapped[str] = mapped_column(
        Enum("activa", "liquidada", name="deuda_estatus"), nullable=False, default="activa")
