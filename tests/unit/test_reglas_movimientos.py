"""Reglas de negocio de ingresos y gastos, sin HTTP ni base de datos."""
from datetime import date

import pytest

from app.core.errores import ApiError
from app.services.movimientos import validar_movimiento

F = date(2026, 1, 5)


def codigo(*args):
    try:
        validar_movimiento(*args)
    except ApiError as e:
        return e.codigo
    return None


@pytest.mark.parametrize("args", [
    ("gasto", "fijo", "mensual", F, None, 1),
    ("gasto", "variable", "unico", F, None, 1),
    ("ingreso", None, "quincenal", F, None, None),
])
def test_combinaciones_validas(args):
    assert codigo(*args) is None


@pytest.mark.parametrize("args,esperado", [
    (("gasto", "variable", "mensual", F, None, 1), "VARIABLE_DEBE_SER_UNICO"),
    (("gasto", "fijo", "unico", F, None, 1), "FIJO_NO_PUEDE_SER_UNICO"),
    (("gasto", None, "mensual", F, None, 1), "CLASE_REQUERIDA"),
    (("gasto", "fijo", "mensual", F, None, None), "CATEGORIA_REQUERIDA"),
    (("gasto", "fijo", "mensual", F, date(2025, 12, 31), 1), "FECHA_FIN_INVALIDA"),
    (("ingreso", "fijo", "quincenal", F, None, None), "CAMPO_NO_APLICA"),
    (("ingreso", None, "quincenal", F, None, 3), "CAMPO_NO_APLICA"),
])
def test_combinaciones_invalidas(args, esperado):
    assert codigo(*args) == esperado
