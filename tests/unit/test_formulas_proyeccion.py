"""Fórmulas 1, 2 y 3 de T25 comparadas con la hoja de referencia T26 (sin base de datos ni HTTP)."""
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.services import formulas as f

D = Decimal


def r2(valor: Decimal) -> Decimal:
    return valor.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def perfil_t26(meses: int = 12, **cambios) -> f.EntradaProyeccion:
    """Perfil de ejemplo de T25 / T26: ingreso 20,000, gastos 8,000 + 4,000, ahorro 5,000,
    tarjetas A y B y dos MSI."""
    datos = dict(
        ingresos=f.constante(D(20000), meses),
        gastos_fijos=f.constante(D(8000), meses),
        gastos_variables=f.constante(D(4000), meses),
        ahorro_inicial=D(5000),
        tarjetas=[f.TarjetaEntrada(1, "A", D(20000), D(60000), D("0.60")),
                  f.TarjetaEntrada(2, "B", D(12000), D(30000), D("0.45"))],
        planes_msi=[f.MsiEntrada(1, "MSI 1", D(12000), 12, 4),
                    f.MsiEntrada(2, "MSI 2", D(6000), 6, 3)],
    )
    datos.update(cambios)
    return f.EntradaProyeccion(**datos)


# Tabla de 12 meses de T25 (pagando solo el mínimo y sin compras nuevas)
TABLA_T25 = [
    # mes, pago mín. A, pago mín. B, MSI activos, flujo, acumulado
    (1, "1460.00", "702.00", "2000", "3838.00", "8838.00"),
    (2, "1438.10", "691.47", "2000", "3870.43", "12708.43"),
    (3, "1416.53", "681.10", "2000", "3902.37", "16610.80"),
    (4, "1395.28", "670.88", "1000", "4933.84", "21544.64"),
    (5, "1374.35", "660.82", "1000", "4964.83", "26509.47"),
    (6, "1353.74", "650.91", "1000", "4995.36", "31504.83"),
    (7, "1333.43", "641.14", "1000", "5025.43", "36530.26"),
    (8, "1313.43", "631.53", "1000", "5055.05", "41585.30"),
    (9, "1293.73", "622.05", "0", "6084.22", "47669.52"),
    (10, "1274.32", "612.72", "0", "6112.96", "53782.48"),
    (11, "1255.21", "603.53", "0", "6141.26", "59923.74"),
    (12, "1236.38", "594.48", "0", "6169.14", "66092.89"),
]


@pytest.mark.parametrize("mes,pago_a,pago_b,msi,flujo,acumulado", TABLA_T25)
def test_proyeccion_igual_a_t25_mes_por_mes(mes, pago_a, pago_b, msi, flujo, acumulado):
    m = f.proyectar(perfil_t26()).meses[mes - 1]
    assert r2(m.tarjetas[0].pago) == D(pago_a)
    assert r2(m.tarjetas[1].pago) == D(pago_b)
    assert r2(m.mensualidades_msi) == D(msi)
    assert r2(m.flujo) == D(flujo)
    assert r2(m.acumulado) == D(acumulado)


def test_igual_a_t26_con_precision_completa():
    """Valores que calcula la hoja T26 (pestaña Proyeccion), sin redondear."""
    p = f.proyectar(perfil_t26())
    esperados = {
        "flujo mes 12": (p.meses[11].flujo, D("6169.1438420782")),          # CP-06a
        "acumulado mes 12": (p.meses[11].acumulado, D("66092.8877035318")),  # CP-06b
        "saldo A mes 12": (p.meses[11].tarjetas[0].saldo_fin, D("16682.6393668175")),
        "saldo B mes 12": (p.meses[11].tarjetas[1].saldo_fin, D("10009.5836200905")),
    }
    for nombre, (calculado, hoja) in esperados.items():
        assert abs(calculado - hoja) < D("0.0000001"), nombre


def test_cp05_balance_del_mes_1():
    m = f.proyectar(perfil_t26()).meses[0]
    assert (m.ingresos, m.gastos_fijos, m.gastos_variables) == (20000, 8000, 4000)
    assert m.pagos_tarjetas == D(2162) and m.mensualidades_msi == D(2000) and m.otras_cuotas == 0
    assert m.compromisos == D(4162)
    assert m.flujo == D(3838) and m.acumulado == D(8838)   # CP-05a y CP-05b


def test_indicadores_de_la_proyeccion():
    p = f.proyectar(perfil_t26())
    assert r2(p.flujo_minimo) == D("3838.00")
    assert r2(p.acumulado_minimo) == D("8838.00")
    assert p.meses_en_negativo == 0
    assert r2(p.meses[11].saldo_tarjetas) == D("26692.22")


# ------------------------------------------------------------ Fórmula 1
def test_cp04_mensualidad_pendiente_y_meses_activos():
    mensualidad = f.mensualidad_msi(D(12000), 12)
    assert mensualidad == D(1000)
    assert f.pendiente_msi(mensualidad, 12, 4) == D(8000)
    activos = [t for t in range(1, 13) if f.msi_activo_en_mes(12, 4, t)]
    assert activos == list(range(1, 9))                    # activo los meses 1 a 8


def test_ce07_msi_en_su_ultima_mensualidad():
    assert f.msi_activo_en_mes(6, 5, 1) is True            # CE-07a
    assert f.msi_activo_en_mes(6, 5, 2) is False           # CE-07b
    p = f.proyectar(perfil_t26(planes_msi=[f.MsiEntrada(1, "Último", D(6000), 6, 5)]))
    assert p.meses[0].mensualidades_msi == D(1000) and p.meses[1].mensualidades_msi == 0


def test_msi_liquidado_no_suma():
    p = f.proyectar(perfil_t26(planes_msi=[f.MsiEntrada(1, "Pagado", D(6000), 6, 6)]))
    assert all(m.mensualidades_msi == 0 and m.msi_activos == 0 for m in p.meses)


def test_usa_la_mensualidad_guardada():
    """La mensualidad redondeada que guarda la base (83.33) manda sobre 1000 / 12."""
    plan = f.MsiEntrada(1, "Audífonos", D(1000), 12, 0, mensualidad=D("83.33"))
    p = f.proyectar(perfil_t26(planes_msi=[plan]))
    assert p.meses[0].mensualidades_msi == D("83.33")


# ----------------------------------------------------- Fórmulas 5 y 6
def test_cp01_cp02_interes_y_pago_minimo():
    interes = f.interes_mes(D(20000), D("0.60"))
    assert r2(interes) == D("1160.00")                      # CP-01
    assert r2(f.pago_minimo(D(20000), interes, D(60000))) == D("1460.00")   # CP-02


def test_cp03_gana_el_porcentaje_de_la_linea():
    interes = f.interes_mes(D(2000), D("0.60"))
    assert r2(f.PCT_SALDO_MIN * D(2000) + interes) == D("146.00")           # CP-03b
    assert r2(f.pago_minimo(D(2000), interes, D(60000))) == D("750.00")     # CP-03a


def test_ce01_minimo_no_pasa_de_lo_que_se_debe():
    interes = f.interes_mes(D(500), D("0.60"))
    assert r2(f.pago_minimo(D(500), interes, D(60000))) == D("529.00")


def test_pago_planeado_no_pasa_de_lo_que_se_debe():
    assert f.pago_tarjeta(D(1000), D(50), D(60000), D(5000)) == D(1050)
    assert f.pago_tarjeta(D(1000), D(50), D(60000), D(300)) == D(300)
    assert f.pago_tarjeta(D(0), D(0), D(60000), None) == 0


def test_tarjeta_liquidada_deja_de_pagar():
    tarjeta = f.TarjetaEntrada(1, "Casi pagada", D(500), D(60000), D("0.60"))
    p = f.proyectar(perfil_t26(tarjetas=[tarjeta], planes_msi=[]))
    assert r2(p.meses[0].pagos_tarjetas) == D("529.00")
    assert all(m.pagos_tarjetas == 0 for m in p.meses[1:])


# ------------------------------------------------------ casos borde
def test_sin_deudas():
    p = f.proyectar(perfil_t26(tarjetas=[], planes_msi=[]))
    assert all(m.compromisos == 0 and m.flujo == D(8000) for m in p.meses)
    assert p.meses[-1].acumulado == D(5000 + 8000 * 12)


def test_sin_ingresos_el_dinero_se_va_a_negativo():
    p = f.proyectar(perfil_t26(ingresos=f.constante(D(0), 12), ahorro_inicial=D(0)))
    assert p.meses[0].flujo < 0 and p.meses[0].acumulado < 0
    assert p.meses_en_negativo == 12


def test_recien_registrado_todo_en_cero():
    vacio = f.EntradaProyeccion(ingresos=f.constante(D(0), 12), gastos_fijos=f.constante(D(0), 12),
                                gastos_variables=f.constante(D(0), 12))
    p = f.proyectar(vacio)
    assert all(m.flujo == 0 and m.acumulado == 0 and m.tarjetas == [] for m in p.meses)


def test_otras_cuotas_terminan_al_liquidar_la_deuda():
    deuda = f.DeudaEntrada(1, "Préstamo", D(1000), D(400))
    p = f.proyectar(perfil_t26(tarjetas=[], planes_msi=[], deudas=[deuda]))
    assert [m.otras_cuotas for m in p.meses[:4]] == [D(400), D(400), D(200), D(0)]


def test_otras_cuotas_con_interes():
    deuda = f.DeudaEntrada(1, "Préstamo", D(10000), D(1000), tasa_anual=D("0.12"))
    p = f.proyectar(perfil_t26(tarjetas=[], planes_msi=[], deudas=[deuda]))
    assert all(m.otras_cuotas == D(1000) for m in p.meses[:10])
    assert 0 < p.meses[10].otras_cuotas < D(1000)       # el último pago es menor


def test_ingresos_distintos_por_mes():
    ingresos = [D(20000)] * 11 + [D(30000)]               # p. ej. un aguinaldo en el mes 12
    p = f.proyectar(perfil_t26(ingresos=ingresos))
    assert r2(p.meses[11].flujo) == D("16169.14")


@pytest.mark.parametrize("meses", [2, 25])
def test_horizonte_fuera_de_rango(meses):
    with pytest.raises(ValueError):
        f.proyectar(perfil_t26(meses=30), meses)


def test_listas_mas_cortas_que_el_horizonte():
    with pytest.raises(ValueError):
        f.proyectar(perfil_t26(meses=6), 12)


def test_horizonte_de_24_meses():
    p = f.proyectar(perfil_t26(meses=24), 24)
    assert len(p.meses) == 24 and p.meses[23].mes == 24


# ------------------------------------------- gastos variables estimados
@pytest.mark.parametrize("previos,esperado", [
    ([D(4000), D(4000), D(4000)], D(4000)),
    ([D(3000), D(0), D(5000)], D(4000)),     # el mes sin registros no cuenta
    ([D(0), D(0), D(2500)], D(2500)),
    ([D(0), D(0), D(0)], None),               # sin historial
])
def test_estimar_gastos_variables(previos, esperado):
    assert f.estimar_gastos_variables(previos) == esperado