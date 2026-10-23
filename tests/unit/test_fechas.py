"""Pruebas unitarias de app/services/fechas.py (sin HTTP ni base de datos)."""
from datetime import date

from app.services import fechas


def test_proxima_fecha():
    f = fechas.proxima_fecha
    assert f(10, date(2026, 3, 15)) == date(2026, 4, 10)    # el día ya pasó: mes siguiente
    assert f(30, date(2026, 3, 15)) == date(2026, 3, 30)
    assert f(30, date(2026, 3, 30)) == date(2026, 3, 30)    # hoy es el día
    assert f(31, date(2026, 2, 1)) == date(2026, 2, 28)     # mes corto: último día
    assert f(5, date(2026, 12, 20)) == date(2027, 1, 5)     # cambio de año


def test_ocurrencias_en_mes():
    f = fechas.ocurrencias_en_mes
    assert f("semanal", date(2026, 3, 2), None, 2026, 3) == [date(2026, 3, d) for d in (2, 9, 16, 23, 30)]
    assert f("mensual", date(2026, 1, 31), None, 2026, 2) == [date(2026, 2, 28)]   # día 31 en mes corto
    assert f("quincenal", date(2026, 1, 31), None, 2026, 3) == [date(2026, 3, 1), date(2026, 3, 16)]
    assert f("unico", date(2026, 3, 20), None, 2026, 4) == []
    assert f("mensual", date(2026, 3, 10), date(2026, 3, 31), 2026, 4) == []         # ya terminó
    assert f("mensual", date(2026, 3, 20), None, 2026, 2) == []                      # aún no empieza
    assert f("anual", date(2026, 3, 20), None, 2026, 3) == []                        # no se acepta en la API
