"""Plan de pagos y ahorro estimado (T45, Fórmula 10 de T25), sin base de datos ni HTTP."""
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.services import plan_pagos as pp
from app.services import priorizador as p
from app.services.priorizador import Candidata

D = Decimal
PERIODOS = [(2026, 3)]                     # mes 1 = marzo de 2026, como en las pruebas


def r2(valor) -> Decimal:
    return D(valor).quantize(D("0.01"), rounding=ROUND_HALF_UP)


A = Candidata(tipo="tarjeta", id=1, nombre="Tarjeta A", saldo=D(20000), tasa_anual=D("0.60"),
              limite=D(60000), pendiente_msi=D(8000))
B = Candidata(tipo="tarjeta", id=2, nombre="Tarjeta B", saldo=D(12000), tasa_anual=D("0.45"),
              limite=D(30000), pendiente_msi=D(3000))


def orden(*candidatas):
    return p.ordenar([p.costo(c) for c in candidatas])


T26 = orden(A, B)


# ------------------------------------------------------ CP-12 (T25 / T26)
def test_cp12_plan_avalancha_con_3000_extra():
    sim = pp.simular_plan(T26, D(3000))
    assert sim.meses == 8 and sim.fin == [6, 8]                  # A en el mes 6, B en el 8
    assert r2(sum(sim.intereses)) == D("7338.10")


def test_cp12_escenario_base_solo_minimo():
    base = pp.simular_base(T26)
    assert base.meses == 74 and base.fin == [73, 74]
    assert r2(sum(base.intereses)) == D("70170.38")              # "más de $70,000" (T25)


def test_cp12_ahorro():
    plan = pp.armar_plan(T26, D(3000), D(3838), PERIODOS)
    t = plan.total
    assert (t.meses_plan, t.liquidacion_plan, t.intereses_plan) == (8, "2026-10", D("7338.10"))
    assert (t.meses_base, t.liquidacion_base, t.intereses_base) == (74, "2032-04", D("70170.38"))
    assert t.ahorro == D("62832.28") and t.meses_menos == 66
    assert plan.presupuesto_mensual == D(5162)                   # 1,460 + 702 + 3,000
    assert "te ahorras $62,832.28" in plan.mensaje and plan.avisos == []


# ---------------------------------------------------- reglas de la Fórmula 10
def test_rn20_primero_los_minimos_y_el_extra_a_la_posicion_1():
    mes1 = pp.armar_plan(T26, D(3000), D(3838), PERIODOS).calendario[0]
    a, b = mes1.pagos
    assert (a.clave, a.pago, a.abono_extra) == ("tarjeta-1", D(4460), D(3000))
    assert (b.clave, b.pago, b.abono_extra) == ("tarjeta-2", D(702), D(0))
    assert mes1.total_pagado == D(5162) and mes1.intereses == D(1682)


def test_presupuesto_fijo_lo_que_baja_el_minimo_va_al_extra():
    cal = pp.armar_plan(T26, D(3000), D(3838), PERIODOS).calendario
    assert all(m.total_pagado == D(5162) for m in cal[:7])
    assert cal[1].pagos[0].abono_extra > cal[0].pagos[0].abono_extra


def test_al_liquidar_una_deuda_el_sobrante_pasa_a_la_siguiente_el_mismo_mes():
    mes6 = pp.armar_plan(T26, D(3000), D(3838), PERIODOS).calendario[5]
    a, b = mes6.pagos
    assert a.saldo_final == 0 and b.abono_extra > 0 and mes6.total_pagado == D(5162)
    assert [x.clave for x in pp.armar_plan(T26, D(3000), D(3838),
                                           PERIODOS).calendario[6].pagos] == ["tarjeta-2"]


@pytest.mark.parametrize("extra,meses,intereses,ahorro", [
    (0, 29, "30423.69", "39746.69"),      # mantener los pagos de hoy ya ahorra
    (500, 20, "18937.76", "51232.62"),
    (3000, 8, "7338.10", "62832.28"),
])
def test_extra_mensual(extra, meses, intereses, ahorro):
    t = pp.armar_plan(T26, D(extra), D(3838), PERIODOS).total
    assert (t.meses_plan, t.intereses_plan, t.ahorro) == (meses, D(intereses), D(ahorro))


def test_mas_extra_nunca_ahorra_menos():
    ahorros = [pp.armar_plan(T26, D(x), D(9999), PERIODOS).total.ahorro
               for x in (0, 500, 1000, 3000)]
    assert ahorros == sorted(ahorros)


# ------------------------------------------------------------ extra sugerido
@pytest.mark.parametrize("flujo,esperado", [("3838", 3800), ("99.99", 0), ("-5", 0), (None, 0)])
def test_extra_sugerido(flujo, esperado):
    assert pp.extra_sugerido(None if flujo is None else D(flujo)) == esperado


def test_ce09_extra_mayor_que_lo_que_sobra_avisa():
    plan = pp.armar_plan(T26, D(5000), D(3838), PERIODOS)
    assert [a.codigo for a in plan.avisos] == ["EXCEDENTE_NO_SOSTENIBLE"]
    assert plan.total.meses_plan is not None                      # el plan sí se calcula


def test_req_pd_04_sin_dinero_extra_avisa():
    plan = pp.armar_plan(T26, D(0), D(-1460), PERIODOS)
    assert [a.codigo for a in plan.avisos] == ["SIN_DINERO_EXTRA"]
    assert plan.extra_sugerido == 0


# ------------------------------------------------------------ casos borde
def test_sin_deudas_no_hay_plan():
    assert pp.armar_plan([], D(500), D(3838), PERIODOS) is None


def test_una_sola_deuda():
    t = pp.armar_plan(orden(A), D(3000), D(3838), PERIODOS).total
    assert (t.meses_plan, t.meses_base, t.ahorro) == (6, 73, D("44527.38"))


def test_deuda_cuyo_pago_no_cubre_intereses():
    """CE-02: con el mínimo nunca se liquida; el ahorro no se puede calcular completo."""
    prestamo = Candidata(tipo="deuda", id=3, nombre="Préstamo", saldo=D(50000),
                         tasa_anual=D("0.36"), pago_mensual=D(1000))       # interés 1,500
    sin_extra = pp.armar_plan(orden(prestamo), D(0), D(2000), PERIODOS)
    assert sin_extra.total.meses_plan is None and sin_extra.total.ahorro is None
    assert [a.codigo for a in sin_extra.avisos] == ["BASE_NO_SE_LIQUIDA", "PLAN_NO_SE_LIQUIDA"]
    assert len(sin_extra.calendario) == pp.CALENDARIO_MAX and not sin_extra.calendario_completo
    con_extra = pp.armar_plan(orden(prestamo), D(2000), D(2000), PERIODOS)
    assert con_extra.total.meses_plan == 24 and con_extra.total.intereses_base is None


def test_deuda_sin_pago_mensual_queda_fuera_del_plan():
    sin_pago = Candidata(tipo="deuda", id=4, nombre="Sin pago", saldo=D(10000),
                         tasa_anual=D("0.24"))
    plan = pp.armar_plan(orden(A, sin_pago), D(0), D(3838), PERIODOS)
    assert [d.clave for d in plan.deudas] == ["tarjeta-1"]
    assert "DEUDA_SIN_PAGO_MENSUAL" in [a.codigo for a in plan.avisos]
    assert pp.armar_plan(orden(sin_pago), D(0), D(3838), PERIODOS) is None


def test_el_escenario_y_los_supuestos_van_en_la_respuesta():
    plan = pp.armar_plan(T26, D(0), D(3838), PERIODOS)
    assert plan.escenario_base == "solo_minimo" and "solo el mínimo" in plan.escenario_base_texto
    assert any("compras nuevas" in s and "tasas" in s for s in plan.supuestos)


def test_periodos_pasan_de_un_anio_a_otro():
    assert pp._periodo([(2026, 11)], 3) == "2027-01" and pp._periodo([(2026, 3)], None) is None