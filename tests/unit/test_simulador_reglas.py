"""Simulador de compras (T41): Fórmula 4 de T25 y reglas fijas del veredicto (RN-15 y RN-16),
sin base de datos ni HTTP. Los números salen de los mismos motores de T33 y T35."""
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.schemas.simulacion import EscenarioPedido, SimulacionPedido
from app.services import formulas as f
from app.services import score_reglas
from app.services import score_formulas as s
from app.services.simulador import elegir_menor_impacto, horizonte, veredicto

D = Decimal
REGLAS = score_reglas.leer()


def r2(valor) -> Decimal:
    return D(valor).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def perfil(**cambios) -> f.EntradaProyeccion:
    """Perfil de ejemplo de T25 / T26."""
    datos = dict(
        ingresos=f.constante(D(20000), 12), gastos_fijos=f.constante(D(8000), 12),
        gastos_variables=f.constante(D(4000), 12), ahorro_inicial=D(5000),
        tarjetas=[f.TarjetaEntrada(1, "A", D(20000), D(60000), D("0.60")),
                  f.TarjetaEntrada(2, "B", D(12000), D(30000), D("0.45"))],
        planes_msi=[f.MsiEntrada(1, "MSI 1", D(12000), 12, 4),
                    f.MsiEntrada(2, "MSI 2", D(6000), 6, 3)])
    datos.update(cambios)
    return f.EntradaProyeccion(**datos)


def score_mes1(entrada: f.EntradaProyeccion, pendiente_msi: Decimal) -> s.ResultadoScore:
    m = f.proyectar(entrada).meses[0]
    return s.calcular(s.EntradaScore(
        ingreso=m.ingresos, compromisos=m.compromisos, mensualidades_msi=m.mensualidades_msi,
        flujo=m.flujo, saldo_tarjetas=D(32000), pendiente_msi=pendiente_msi,
        limite_total=D(90000), comportamiento_pago="solo_minimo"), REGLAS)


# ----------------------------------------------- Fórmula 3 con CompraContado
def test_sin_compra_la_proyeccion_no_cambia():
    """La compra de contado es opcional: T33 da lo mismo que antes (CP-05 y CP-06)."""
    p = f.proyectar(perfil())
    assert (p.meses[0].flujo, p.meses[0].acumulado, p.meses[0].compra_contado) == (3838, 8838, 0)
    assert r2(p.meses[11].acumulado) == D("66092.89")


def test_compra_contado_solo_resta_en_su_mes():
    p = f.proyectar(perfil(compras_contado=[D(9000)]))
    assert p.meses[0].compra_contado == 9000 and p.meses[1].compra_contado == 0
    assert p.meses[0].flujo == D(3838 - 9000) and p.meses[0].acumulado == D(-162)
    assert p.meses[0].compromisos == D(4162)          # contado no es compromiso
    assert r2(p.meses[1].flujo) == D("3870.43")        # del mes 2 en adelante, igual que T25


# ------------------------------------------------ CP-10 (Fórmula 4 de T25)
def test_cp10_contado_se_descarta():
    p = f.proyectar(perfil(compras_contado=[D(9000)]))
    assert p.meses_en_negativo >= 1 and p.acumulado_minimo == D(-162)


def test_cp10_doce_msi_score_70():
    plan = f.MsiEntrada(0, "Compra simulada", D(9000), 12, 0)
    entrada = perfil(planes_msi=[*perfil().planes_msi, plan])
    p = f.proyectar(entrada)
    assert p.meses_en_negativo == 0
    assert p.meses[0].mensualidades_msi == D(2750)           # 2,000 + 750
    assert p.meses[0].flujo == D(3088) and p.meses[11].mensualidades_msi == D(750)
    r = score_mes1(entrada, D(11000) + D(9000))              # M ocupa la línea desde el mes 1
    assert r2(r.puntaje_bruto) == D("69.52") and r.puntaje == 70 and r.nivel == "en_revision"


# ----------------------------------------------------------- veredicto
@pytest.mark.parametrize("prioridad", ["alta", "media", "baja"])
def test_rn15_si_el_dinero_no_alcanza_no_es_recomendable(prioridad):
    clave, regla, _ = veredicto(prioridad, 1, "saludable", "saludable")
    assert (clave, regla) == ("no_recomendable", "RN-15")


@pytest.mark.parametrize("prioridad,nivel_sim,nivel_actual,esperado", [
    ("alta", "critico", "saludable", "recomendable"),          # aunque el índice baje
    ("media", "en_revision", "saludable", "recomendable"),
    ("media", "en_riesgo", "en_revision", "con_precaucion"),
    ("media", "critico", "en_riesgo", "con_precaucion"),
    ("baja", "en_revision", "en_revision", "recomendable"),    # se mantiene el nivel
    ("baja", "en_revision", "saludable", "con_precaucion"),    # baja de nivel
    ("baja", "saludable", "en_revision", "recomendable"),      # no baja
])
def test_rn16_depende_de_la_prioridad(prioridad, nivel_sim, nivel_actual, esperado):
    clave, regla, razon = veredicto(prioridad, 0, nivel_sim, nivel_actual)
    assert (clave, regla) == (esperado, "RN-16") and razon


# -------------------------------------------------------- menor impacto
def test_menor_impacto_mayor_score_entre_los_viables():
    # (id, meses en negativo, acumulado mínimo, puntaje)
    candidatos = [("contado", 1, D(-162), 53), ("msi-1-6", 0, D(7338), 64),
                  ("msi-1-12", 0, D(8088), 70)]
    assert elegir_menor_impacto(candidatos) == "msi-1-12"


def test_menor_impacto_empate_gana_mayor_acumulado_minimo():
    assert elegir_menor_impacto([("a", 0, D(100), 70), ("b", 0, D(500), 70)]) == "b"


def test_menor_impacto_si_ninguno_alcanza():
    """RN-15: con prioridad alta se indica la forma de pago con menor impacto."""
    candidatos = [("contado", 3, D(-9000), 30), ("msi-1-12", 1, D(-200), 40),
                  ("msi-1-6", 1, D(-800), 45)]
    assert elegir_menor_impacto(candidatos) == "msi-1-12"


def test_menor_impacto_sin_candidatos():
    assert elegir_menor_impacto([]) is None


# -------------------------------------------------------- horizonte y pedido
@pytest.mark.parametrize("plazos,esperado", [([], 12), ([3, 6], 12), ([18], 18), ([36], 24),
                                             ([99], 12)])
def test_horizonte(plazos, esperado):
    escenarios = [EscenarioPedido(tipo="contado")] + [
        EscenarioPedido(tipo="msi", tarjeta_id=1, meses=n) for n in plazos]
    assert horizonte(escenarios) == esperado


@pytest.mark.parametrize("escenario", [
    {"tipo": "msi", "meses": 12},                       # sin tarjeta
    {"tipo": "msi", "tarjeta_id": 1},                   # sin meses
    {"tipo": "contado", "meses": 3},                    # contado no lleva plazo
    {"tipo": "transferencia"},
])
def test_pedido_invalido(escenario):
    with pytest.raises(ValueError):
        SimulacionPedido(descripcion="Laptop", precio=9000, prioridad="media",
                         escenarios=[escenario])


@pytest.mark.parametrize("cambio", [{"precio": 0}, {"precio": -5}, {"prioridad": "urgente"},
                                    {"escenarios": []}, {"ahorro_inicial": -1}])
def test_pedido_invalido_campos(cambio):
    datos = dict(descripcion="Laptop", precio=9000, prioridad="media",
                 escenarios=[{"tipo": "contado"}])
    datos.update(cambio)
    with pytest.raises(ValueError):
        SimulacionPedido(**datos)