import calendar
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.core.config import settings

CENTAVO = Decimal("0.01")


def hoy_mx() -> date:
    """Fecha de hoy con hora de México (T17: 'con hora de México')."""
    return datetime.now(ZoneInfo(settings.zona_horaria)).date()


def ajustar_dia(anio: int, mes: int, dia: int) -> date:
    """Si el mes tiene menos días que `dia`, usa el último día del mes (T18 §4.3)."""
    return date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))


def proxima_fecha(dia: int, hoy: date) -> date:
    """Primera fecha con ese día del mes que sea hoy o posterior."""
    este_mes = ajustar_dia(hoy.year, hoy.month, dia)
    if este_mes >= hoy:
        return este_mes
    anio, mes = (hoy.year + 1, 1) if hoy.month == 12 else (hoy.year, hoy.month + 1)
    return ajustar_dia(anio, mes, dia)


def a_centavos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
