"""Archivo de configuración del score (app/core/reglas_score.json): pesos que suman 100 y
validaciones que impiden arrancar con reglas que no cumplen T25."""
import copy
import json
from decimal import Decimal

import pytest

from app.services import score_reglas
from app.services.score_reglas import FACTORES, ReglasInvalidas, construir


@pytest.fixture
def crudo():
    with open(score_reglas.RUTA_REGLAS, encoding="utf-8") as archivo:
        return json.load(archivo)


def test_el_archivo_vigente_es_valido_y_suma_100():
    reglas = score_reglas.leer()
    assert reglas.suma_pesos == Decimal(100)
    assert reglas.version_modelo
    assert tuple(reglas.factores) == FACTORES                 # orden de T25


def test_pesos_de_t25():
    pesos = {c: f.peso for c, f in score_reglas.leer().factores.items()}
    assert pesos == {"relacion_deuda_ingreso": 30, "utilizacion_credito": 25, "flujo_libre": 25,
                     "carga_msi": 10, "comportamiento_pago": 10}


def test_puntos_de_referencia_de_t25():
    f = score_reglas.leer().factores
    assert f["relacion_deuda_ingreso"].puntos_referencia == ((0, 100), (30, 100), (40, 50), (50, 0))
    assert f["utilizacion_credito"].puntos_referencia == (
        (0, 100), (10, 100), (30, 80), (50, 40), (100, 0))
    assert f["flujo_libre"].puntos_referencia == ((-20, 0), (0, 40), (20, 100))
    assert f["carga_msi"].puntos_referencia == ((0, 100), (10, 100), (25, 0))
    assert f["comportamiento_pago"].subpuntajes_categoria == {
        "pago_total": 100, "mas_del_minimo": 60, "solo_minimo": 20, "con_atraso": 0}
    assert score_reglas.leer().tope_riesgo_inmediato == 59


def test_cada_peso_esta_justificado():
    for f in score_reglas.leer().factores.values():
        assert len(f.justificacion_peso) > 40, f.clave
        assert f.fuente_puntos, f.clave


def test_se_puede_ajustar_sin_tocar_el_codigo(crudo):
    datos = copy.deepcopy(crudo)
    datos["factores"][0]["peso"] = 20                         # DTI 20
    datos["factores"][2]["peso"] = 35                         # flujo libre 35
    reglas = construir(datos)
    assert reglas.factores["relacion_deuda_ingreso"].peso == 20
    assert reglas.suma_pesos == 100


def _con(crudo, cambio):
    datos = copy.deepcopy(crudo)
    cambio(datos)
    return datos


@pytest.mark.parametrize("cambio,mensaje", [
    (lambda d: d["factores"][0].update(peso=29), "suman 99"),
    (lambda d: d["factores"].pop(), "faltan los factores"),
    (lambda d: d["factores"][0].update(clave="otro"), "desconocido"),
    (lambda d: d["factores"].append(dict(d["factores"][0])), "repetido"),
    (lambda d: d["factores"][0].update(peso=-5), "negativo"),
    (lambda d: d["factores"][0].update(justificacion_peso=""), "por qué pesa"),
    (lambda d: d["factores"][0].update(puntos_referencia=[[30, 100], [0, 100]]), "menor a mayor"),
    (lambda d: d["factores"][0].update(puntos_referencia=[[0, 120], [30, 100]]), "entre 0 y 100"),
    (lambda d: d["factores"][0].update(puntos_referencia=[[0, 100]]), "al menos 2"),
    (lambda d: d["factores"][4]["subpuntajes_categoria"].pop("con_atraso"), "debe definir"),
    (lambda d: d.update(comportamiento_por_defecto="nunca"), "comportamiento_por_defecto"),
    (lambda d: d.update(tope_riesgo_inmediato=120), "tope_riesgo_inmediato"),
    (lambda d: d.update(version_modelo=""), "version_modelo"),
])
def test_reglas_invalidas_no_se_aceptan(crudo, cambio, mensaje):
    with pytest.raises(ReglasInvalidas) as e:
        construir(_con(crudo, cambio))
    assert mensaje in str(e.value)