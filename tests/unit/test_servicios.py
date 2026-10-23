"""Servicios probados directamente con una sesión de base de datos, sin pasar por HTTP."""
from datetime import date
from decimal import Decimal

import pytest

from app.core.errores import ApiError
from app.models import Categoria, Usuario
from app.schemas.categoria import CategoriaCrear
from app.schemas.deuda import DeudaCrear, DeudaEditar
from app.schemas.movimiento import MovimientoCrear
from app.schemas.tarjeta import TarjetaCrear
from app.services import categorias, deudas, movimientos, tarjetas
from tests.conftest import TestSession


def _usuario(db, correo):
    u = Usuario(nombre="Prueba", correo=correo, contrasena_hash="x", moneda="MXN")
    db.add(u)
    db.commit()
    return u


def _tarjeta():
    return TarjetaCrear(nombre="BBVA", banco="BBVA", limite_credito=Decimal("20000"),
                        dia_corte=10, dia_pago=30)


def test_registro_ajeno_se_trata_como_inexistente():
    with TestSession() as db:
        u1, u2 = _usuario(db, "uno@ejemplo.com"), _usuario(db, "dos@ejemplo.com")
        t = tarjetas.crear(db, u1, _tarjeta())
        assert tarjetas.obtener(db, u1, t.id).id == t.id
        with pytest.raises(ApiError) as e:
            tarjetas.obtener(db, u2, t.id)
        assert e.value.status == 404 and e.value.codigo == "TARJETA_NO_ENCONTRADA"


def test_tarjeta_calcula_campos_derivados():
    with TestSession() as db:
        u = _usuario(db, "uno@ejemplo.com")
        out = tarjetas.crear(db, u, _tarjeta().model_copy(update={"saldo_actual": Decimal("5000")}))
        assert out.porcentaje_limite_usado == 25.0
        assert out.credito_disponible == Decimal("15000")
        assert out.proxima_fecha_pago == date(2026, 3, 30)   # "hoy" = 15-mar-2026


def test_categorias_no_admiten_duplicados():
    with TestSession() as db:
        u = _usuario(db, "uno@ejemplo.com")
        db.add(Categoria(usuario_id=None, nombre="Vivienda"))
        db.commit()
        with pytest.raises(ApiError) as e:
            categorias.crear(db, u, CategoriaCrear(nombre="vivienda"))
        assert e.value.codigo == "CATEGORIA_DUPLICADA"
        categorias.crear(db, u, CategoriaCrear(nombre="Mascotas"))
        assert [(c.nombre, c.base) for c in categorias.listar(db, u)] == [
            ("Vivienda", True), ("Mascotas", False)]


def test_deuda_cambia_de_estatus_segun_el_saldo():
    with TestSession() as db:
        u = _usuario(db, "uno@ejemplo.com")
        d = deudas.crear(db, u, DeudaCrear(nombre="Prestamo", tipo="otro",
                                           monto_original=Decimal("100"), saldo_actual=Decimal("0")))
        assert d.estatus == "liquidada"
        d = deudas.editar(db, u, d.id, DeudaEditar(saldo_actual=Decimal("50")))
        assert d.estatus == "activa"


def test_movimientos_totales_del_mes():
    with TestSession() as db:
        u = _usuario(db, "uno@ejemplo.com")
        cat = Categoria(usuario_id=None, nombre="Vivienda")
        db.add(cat)
        db.commit()
        renta = movimientos.crear(db, u, MovimientoCrear(
            tipo="gasto", concepto="Renta", monto=Decimal("8000"), frecuencia="mensual",
            fecha=date(2026, 1, 5), clase="fijo", categoria_id=cat.id))
        assert renta.id.startswith("gasto-") and renta.categoria == "Vivienda"
        mes = movimientos.listar_mes(db, u, "2026-03")
        assert mes.totales.gastos_fijos == Decimal("8000")
        assert mes.totales.balance == Decimal("-8000")
        assert [m.fecha_ocurrencia for m in mes.movimientos] == [date(2026, 3, 5)]


def test_id_de_movimiento_mal_formado_es_404():
    with TestSession() as db:
        u = _usuario(db, "uno@ejemplo.com")
        for malo in ("abc", "gasto-", "gasto-9999", "otro-1"):
            with pytest.raises(ApiError) as e:
                movimientos.obtener(db, u, malo)
            assert e.value.status == 404
