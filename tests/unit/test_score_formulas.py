"""Índice de Salud Financiera comparado con T25 y la hoja T26 (sin base de datos ni HTTP)."""
import copy
import json
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.services import score_reglas
from app.services import score_formulas as s

D = Decimal
REGLAS = score_reglas.leer()


def r2(valor):
    return D(valor).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def entrada(**cambios) -> s.EntradaScore:
    """Perfil de ejemplo de T25 / T26 (mes 1)."""
    datos = dict(ingreso=D(20000), compromisos=D(4162), mensualidades_msi=D(2000), flujo=D(3838),
                 saldo_tarjetas=D(32000), pendiente_msi=D(11000), limite_total=D(90000),
                 comportamiento_pago="solo_minimo")
    datos.update(cambios)
    return s.EntradaScore(**datos)


def factor(resultado, clave):
    return next(f for f in resultado.factores if f.clave == clave)


# -------------------------------------------------- ejemplo de T25 (CP-09)
# clave, valor %, subpuntaje, aporte, puntos perdidos (tabla "Ejemplo con el perfil de ejemplo")
TABLA_T25 = [
    ("relacion_deuda_ingreso", "20.81", "100.00", "30.00", "0.00"),
    ("utilizacion_credito", "47.78", "44.44", "11.11", "13.89"),
    ("flujo_libre", "19.19", "97.57", "24.39", "0.61"),
    ("carga_msi", "10.00", "100.00", "10.00", "0.00"),
    ("comportamiento_pago", None, "20.00", "2.00", "8.00"),
]


@pytest.mark.parametrize("clave,valor,subpuntaje,aporte,perdidos", TABLA_T25)
def test_desglose_igual_a_t25(clave, valor, subpuntaje, aporte, perdidos):
    f = factor(s.calcular(entrada(), REGLAS), clave)
    if valor is not None:
        assert r2(f.valor) == D(valor)
    assert r2(f.subpuntaje) == D(subpuntaje)
    assert r2(f.aporte) == D(aporte)
    assert r2(f.puntos_perdidos) == D(perdidos)


def test_cp09_score_del_perfil_de_ejemplo():
    r = s.calcular(entrada(), REGLAS)
    assert r2(r.puntaje_bruto) == D("77.50")                          # CP-09a
    assert abs(r.puntaje_bruto - D("77.5036111111111")) < D("1e-9")   # hoja T26, Score!C12
    assert r.puntaje == 78                                            # CP-09b
    assert (r.nivel, r.nivel_texto) == ("en_revision", "En revisión")  # 60–79 (T17)
    assert not r.tope_aplicado and r.motivo_tope is None
    assert r.version_modelo == REGLAS.version_modelo


def test_aportes_suman_el_score_y_perdidos_el_resto():
    r = s.calcular(entrada(), REGLAS)
    assert sum(f.aporte for f in r.factores) == r.puntaje_bruto
    assert r2(sum(f.puntos_perdidos for f in r.factores)) == D("22.50")
    assert sum(f.peso_efectivo for f in r.factores) == 100


def test_regla4_orden_de_mejora():
    r = s.calcular(entrada(), REGLAS)
    assert r.orden_mejora == ["utilizacion_credito", "comportamiento_pago", "flujo_libre"]


# ------------------------------------------------------- subpuntajes (CP-08)
@pytest.mark.parametrize("clave,valor,esperado", [
    ("relacion_deuda_ingreso", "35", "75.00"),         # CP-08a
    ("flujo_libre", "-10", "20.00"),                   # CP-08b
    ("carga_msi", "17.5", "50.00"),                    # CP-08c
    ("utilizacion_credito", "47.7777777777", "44.44"),  # CP-08d
    ("utilizacion_credito", "120", "0.00"),            # CE-10: más de 100 % vale 0
    ("flujo_libre", "-35", "0.00"),                    # debajo del primer punto
    ("flujo_libre", "45", "100.00"),                   # arriba del último punto
    ("relacion_deuda_ingreso", "0", "100.00"),
])
def test_subpuntajes_por_interpolacion(clave, valor, esperado):
    puntos = REGLAS.factores[clave].puntos_referencia
    assert r2(s.interpolar(D(valor), puntos)) == D(esperado)


@pytest.mark.parametrize("categoria,esperado", [
    ("pago_total", 100), ("mas_del_minimo", 60), ("solo_minimo", 20), ("con_atraso", 0)])
def test_comportamiento_de_pago(categoria, esperado):
    f = factor(s.calcular(entrada(comportamiento_pago=categoria), REGLAS), "comportamiento_pago")
    assert f.subpuntaje == esperado and f.categoria == categoria


# --------------------------------------------------------- casos especiales
def test_ce03_sin_ingreso_no_hay_score():
    with pytest.raises(ValueError):
        s.calcular(entrada(ingreso=D(0)), REGLAS)


def test_ce04_sin_tarjetas_se_reparten_los_pesos():
    # DTI 15 % · flujo 10 % · MSI 0 % · pago total → (30 + 17.5 + 10 + 10) ÷ 0.75 = 90
    r = s.calcular(s.EntradaScore(D(10000), D(1500), D(0), D(1000), D(0), D(0), D(0),
                                  "pago_total"), REGLAS)
    assert r.puntaje_bruto == D(90) and r.puntaje == 90 and r.nivel == "saludable"
    util = factor(r, "utilizacion_credito")
    assert not util.disponible and util.valor is None and util.subpuntaje is None
    assert util.aporte == 0 and util.peso_efectivo == 0 and "no tienes tarjetas" in util.explicacion.lower()
    assert r2(factor(r, "relacion_deuda_ingreso").peso_efectivo) == D("40.00")   # 30 ÷ 75
    assert "utilizacion_credito" not in r.orden_mejora


def test_ce05_flujo_negativo_aplica_tope():
    # DTI 20 % · utilización 5 % · flujo −1 % · MSI 0 % · pago total → 84.5, tope 59
    r = s.calcular(s.EntradaScore(D(10000), D(2000), D(0), D(-100), D(500), D(0), D(10000),
                                  "pago_total"), REGLAS)
    assert r.puntaje_bruto == D("84.5")                       # CE-05a
    assert r.puntaje == 59 and r.nivel == "en_riesgo"        # CE-05b
    assert r.tope_aplicado and r.motivo_tope == "flujo_negativo"


def test_pago_con_atraso_aplica_tope():
    r = s.calcular(entrada(comportamiento_pago="con_atraso", compromisos=D(2000),
                           saldo_tarjetas=D(1000), pendiente_msi=D(0), mensualidades_msi=D(0),
                           flujo=D(6000)), REGLAS)
    assert r.puntaje_bruto > 59 and r.puntaje == 59 and r.motivo_tope == "pago_con_atraso"


def test_tope_no_sube_un_score_bajo():
    r = s.calcular(entrada(flujo=D(-5000), compromisos=D(15000)), REGLAS)
    assert r.puntaje < 59 and not r.tope_aplicado and r.motivo_tope is None


@pytest.mark.parametrize("bruto,esperado", [("77.5", 78), ("77.49", 77), ("59.5", 60), ("0.4", 0)])
def test_ce06_redondeo(bruto, esperado):
    assert s.redondear(D(bruto)) == esperado


@pytest.mark.parametrize("puntaje,nivel", [
    (100, "saludable"), (80, "saludable"), (79, "en_revision"), (60, "en_revision"),
    (59, "en_riesgo"), (40, "en_riesgo"), (39, "critico"), (0, "critico")])
def test_niveles_fijos_de_t17(puntaje, nivel):
    assert s.nivel_de(puntaje)[0] == nivel


# ------------------------------------------------------------- desglose
def test_cada_factor_explica_su_resultado():
    r = s.calcular(entrada(), REGLAS)
    textos = {f.clave: f.explicacion for f in r.factores}
    assert "20.8 %" in textos["relacion_deuda_ingreso"]
    assert "47.8 %" in textos["utilizacion_credito"] and "44 de 100" in textos["utilizacion_credito"]
    assert "19.2 %" in textos["flujo_libre"]
    assert "solo el mínimo" in textos["comportamiento_pago"]
    assert all(f.como_mejorar and f.justificacion_peso and f.formula for f in r.factores)
    assert factor(r, "utilizacion_credito").datos == {
        "saldo_tarjetas": D(32000), "pendiente_msi": D(11000), "limite_total": D(90000)}


def test_flujo_negativo_se_explica():
    f = factor(s.calcular(entrada(flujo=D(-2000)), REGLAS), "flujo_libre")
    assert "superan tu ingreso en 10.0 %" in f.explicacion


def test_los_pesos_vienen_de_la_configuracion():
    """Cambiar el archivo cambia el score sin tocar el código."""
    with open(score_reglas.RUTA_REGLAS, encoding="utf-8") as archivo:
        datos = json.load(archivo)
    datos = copy.deepcopy(datos)
    datos["factores"][1]["peso"] = 15         # utilización 15
    datos["factores"][4]["peso"] = 20         # comportamiento 20
    otras = score_reglas.construir(datos)
    r = s.calcular(entrada(), otras)
    # 30 + 0.15 × 44.44 + 24.39 + 10 + 0.20 × 20 = 75.06
    assert r2(r.puntaje_bruto) == D("75.06") and r.puntaje == 75