"""Archivo, lectura del PDF y conversión al contrato de /extraer (sin HTTP ni IA)."""
import io
from decimal import Decimal

import pytest

from app.core.errores import ApiError
from app.services.estados_cuenta import archivo, pdf
from app.services.estados_cuenta.conversion import a_contrato, quitar_compras_a_meses_repetidas
from app.services.estados_cuenta.esquema_ia import EstadoCuentaIA
from tests.utilidades_ia import LINEAS_ESTADO, pdf_minimo, respuesta


def _plan(actual, total, original):
    return {"mensualidad_actual": actual, "meses_totales": total, "monto_original": original,
            "saldo_pendiente": None}


def _mov(fecha, concepto, monto, modalidad="contado", meses=None, tipo="compra"):
    return {"fecha": fecha, "concepto": concepto, "monto": monto, "tipo": tipo,
            "modalidad": modalidad, "meses": meses}


# ------------------------------------------------------------------ archivo
@pytest.mark.parametrize("contenido,tipo", [(b"%PDF-1.4 ok", "text/plain"), (b"hola", "application/pdf"),
                                            (b"%PDF-" + b"0" * 20, "application/pdf")])
def test_el_archivo_se_cierra_aunque_sea_invalido(contenido, tipo):
    f = io.BytesIO(contenido)
    with pytest.raises(ApiError) as error:
        archivo.leer(f, tipo, max_bytes=10)
    assert error.value.codigo == "ARCHIVO_INVALIDO"
    assert f.closed


def test_el_archivo_se_cierra_al_leerlo_bien():
    f = io.BytesIO(b"%PDF-1.4 contenido")
    assert archivo.leer(f, "application/pdf; charset=binary", max_bytes=100) == b"%PDF-1.4 contenido"
    assert f.closed


def test_lee_el_texto_del_pdf_en_memoria():
    assert "ESTADO DE CUENTA" in pdf.leer_texto(pdf_minimo(LINEAS_ESTADO))


def test_pdf_sin_texto():
    with pytest.raises(pdf.PdfIlegible):
        pdf.leer_texto(pdf_minimo([]))


# ---------------------------------------------------------------- conversión
def test_quita_la_compra_completa_si_ya_esta_su_mensualidad():
    # Como en BBVA: la compra completa (619) y su mensualidad (104) del mismo plan
    datos = {"movimientos": [_mov("2026-08-11", "CINEPOLIS DULCERIA", 619.0, "msi", _plan(1, 6, 619.0)),
                             _mov("2026-09-04", "01 DE 06 CINEPOLIS", 104.0, "msi", _plan(1, 6, 619.0)),
                             _mov("2026-08-12", "OXXO", 50.0)]}
    assert quitar_compras_a_meses_repetidas(datos) == 1
    assert [m["monto"] for m in datos["movimientos"]] == [104.0, 50.0]


def test_no_quita_mensualidades_de_compras_distintas():
    # Como en Mercado Pago: dos compras distintas de 576 pagadas en mensualidades de 144
    datos = {"movimientos": [_mov("2026-08-03", "MERCADOLIBRE", 144.0, "msi", _plan(n, 4, 576.0))
                             for n in (4, 2, 3, 1, 1)]}
    assert quitar_compras_a_meses_repetidas(datos) == 0


def test_movimientos_son_solo_cargos():
    estado = EstadoCuentaIA.model_validate(respuesta(movimientos=[
        _mov("2026-08-02", "SUPER", 100.0),
        _mov("2026-08-03", "TIENDA", 50.0, "msi", _plan(1, 3, 150.0)),
        _mov("2026-08-04", "LAPTOP", 800.0, "meses_con_intereses", _plan(1, 12, 9000.0)),
        _mov("2026-08-05", "COMISION ANUAL", 600.0, None, tipo="comision"),
        _mov("2026-08-06", "PAGO", -500.0, None, tipo="pago"),
        _mov("2026-08-07", "DEVOLUCION", -40.0, "contado", tipo="devolucion"),
    ]))
    salida = a_contrato(estado)
    assert [m.concepto for m in salida.movimientos] == ["SUPER", "LAPTOP", "COMISION ANUAL"]
    assert [m.descripcion for m in salida.msi] == ["TIENDA"]


def test_msi_sin_detalle_del_plan_va_en_null():
    estado = EstadoCuentaIA.model_validate(respuesta(movimientos=[_mov("2026-08-05", "TIENDA", 250.0, "msi")]))
    msi = a_contrato(estado).msi[0]
    assert (msi.descripcion, msi.monto_total, msi.meses, msi.mensualidades_pagadas) == ("TIENDA", None, None, None)


def test_montos_a_dos_decimales_y_dias_del_mes():
    estado = EstadoCuentaIA.model_validate(respuesta(
        fecha_corte="2026-02-28", fecha_limite_pago="2026-03-05",
        pagos={"total_a_pagar_periodo": 3750.456, "pago_para_no_generar_intereses": 1250.004,
               "pago_minimo": 299.995, "pago_minimo_mas_msi": None}))
    tarjeta = a_contrato(estado).tarjeta
    assert (tarjeta.dia_corte, tarjeta.dia_limite_pago) == (28, 5)
    assert (tarjeta.saldo_actual, tarjeta.pago_minimo, tarjeta.pago_no_intereses) == (
        Decimal("3750.46"), Decimal("300.00"), Decimal("1250.00"))
