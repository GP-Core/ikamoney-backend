"""Reglas de negocio de los planes MSI, sin HTTP ni base de datos."""
from datetime import date
from decimal import Decimal

import pytest

from app.core.errores import ApiError
from app.services.msi import calcular_estatus, mensualidad_calculada, validar_plan

COMPRA = date(2026, 1, 10)   # "hoy" en las pruebas es 15-mar-2026 (ver conftest)


def codigo(*args):
    try:
        validar_plan(*args)
    except ApiError as e:
        return e.codigo
    return None


def test_mensualidad_calculada_redondea_a_centavos():
    assert mensualidad_calculada(Decimal("12000"), 12) == Decimal("1000.00")
    assert mensualidad_calculada(Decimal("1000"), 12) == Decimal("83.33")


def test_plan_valido():
    assert codigo(Decimal("12000"), 12, 2, Decimal("1000"), COMPRA) is None
    # 83.33 × 12 = 999.96: dentro de la tolerancia de 1 centavo por mensualidad
    assert codigo(Decimal("1000"), 12, 0, Decimal("83.33"), COMPRA) is None


@pytest.mark.parametrize("args,esperado", [
    ((Decimal("12000"), 12, 13, Decimal("1000"), COMPRA), "MSI_PAGADAS_EXCEDEN"),
    ((Decimal("12000"), 12, 0, Decimal("0"), COMPRA), "MONTO_INVALIDO"),
    ((Decimal("12000"), 12, 0, Decimal("900"), COMPRA), "MSI_MONTOS_INCOHERENTES"),
    ((Decimal("12000"), 12, 0, Decimal("1000"), date(2026, 3, 16)), "FECHA_INVALIDA"),
])
def test_plan_invalido(args, esperado):
    assert codigo(*args) == esperado


@pytest.mark.parametrize("solicitado,pagadas,num,esperado", [
    (None, 2, 12, "activo"),
    (None, 12, 12, "liquidado"),
    ("cancelado", 12, 12, "cancelado"),   # lo cancelado no se liquida solo
    ("activo", 3, 12, "activo"),
])
def test_calcular_estatus(solicitado, pagadas, num, esperado):
    assert calcular_estatus(solicitado, pagadas, num) == esperado
