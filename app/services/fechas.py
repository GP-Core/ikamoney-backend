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


def ocurrencias_en_mes(frecuencia: str, inicio: date, fin: date | None,
                       anio: int, mes: int) -> list[date]:
    """Fechas en que cae un ingreso/gasto dentro de un mes (T17: 'incluye los recurrentes').

    Respeta fecha_inicio y fecha_fin. Quincenal = dos veces al mes (el día de `inicio`
    ajustado a la 1.ª quincena, y 15 días después).
    """
    ultimo = calendar.monthrange(anio, mes)[1]
    if frecuencia == "unico":
        candidatas = [inicio]
    elif frecuencia == "mensual":
        candidatas = [ajustar_dia(anio, mes, inicio.day)]
    elif frecuencia == "quincenal":
        d1 = (inicio.day - 1) % 15 + 1
        candidatas = [date(anio, mes, d1), ajustar_dia(anio, mes, d1 + 15)]
    elif frecuencia == "semanal":
        candidatas = [date(anio, mes, d) for d in range(1, ultimo + 1)
                      if (date(anio, mes, d) - inicio).days % 7 == 0]
    else:  # 'anual' no se acepta en la API (T17 solo lista 4 frecuencias)
        return []
    return [c for c in candidatas
            if c.year == anio and c.month == mes
            and c >= inicio and (fin is None or c <= fin)]