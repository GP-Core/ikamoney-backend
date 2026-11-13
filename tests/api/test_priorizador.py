"""GET /api/v1/priorizador: deudas ordenadas por costo real (T43). "Hoy" es el 15 de marzo
de 2026."""
import pytest
from sqlalchemy import func, select

from app.models import Deuda, ScoreHistorial, Tarjeta
from tests.conftest import TestSession

URL = "/api/v1/priorizador"


def tarjeta(nombre, saldo, limite, tasa):
    cuerpo = {"nombre": nombre, "banco": "Banco", "limite_credito": limite, "saldo_actual": saldo,
              "dia_corte": 10, "dia_pago": 30}
    if tasa is not None:
        cuerpo["tasa_anual"] = tasa
    return cuerpo


def deuda(nombre, saldo, tasa, pago=None, tipo="prestamo_personal"):
    cuerpo = {"nombre": nombre, "tipo": tipo, "monto_original": max(saldo, 1),
              "saldo_actual": saldo, "tasa_anual": tasa}
    if pago is not None:
        cuerpo["pago_mensual"] = pago
    return cuerpo


def post(client, h, ruta, cuerpo):
    r = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def contar(modelo) -> int:
    with TestSession() as db:
        return db.scalar(select(func.count()).select_from(modelo))


@pytest.fixture
def perfil_t26(client, h):
    """Tarjetas A y B con sus MSI, como en T25 / T26."""
    a = post(client, h, "tarjetas", tarjeta("Tarjeta A", 20000, 60000, 60))
    b = post(client, h, "tarjetas", tarjeta("Tarjeta B", 12000, 30000, 45))
    post(client, h, "msi", {"tarjeta_id": a["id"], "descripcion": "MSI 1", "monto_original": 12000,
                            "num_mensualidades": 12, "mensualidades_pagadas": 4,
                            "fecha_compra": "2025-11-10"})
    post(client, h, "msi", {"tarjeta_id": b["id"], "descripcion": "MSI 2", "monto_original": 6000,
                            "num_mensualidades": 6, "mensualidades_pagadas": 3,
                            "fecha_compra": "2025-12-10"})
    return a, b


def test_sin_token_401(client):
    r = client.get(URL)
    assert r.status_code == 401 and r.json()["codigo"] == "NO_AUTENTICADO"


# ------------------------------------------------------ CP-11 (T25 / T26)
def test_cp11_ranking_igual_a_t25(client, h, perfil_t26):
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "calculado" and d["periodo"] == "2026-03"
    a, b = d["ranking"]
    assert (a["posicion"], a["nombre"], a["tasa_mensual"], a["interes_mes"], a["utilizacion"]) == \
        (1, "Tarjeta A", 5.8, 1160.0, 46.67)
    assert (b["posicion"], b["nombre"], b["tasa_mensual"], b["interes_mes"], b["utilizacion"]) == \
        (2, "Tarjeta B", 4.35, 522.0, 50.0)
    assert (a["costo_anual_compuesto"], b["costo_anual_compuesto"]) == (96.71, 66.69)
    assert (a["pago_minimo"], b["pago_minimo"]) == (1460.0, 702.0)
    assert (a["accion"], b["accion"]) == ("abonar_extra", "pagar_minimo")              # RN-20
    assert a["comparacion"] is None and b["comparacion"]["criterio"] == "tasa"
    assert "$1,160.00" in a["razon"] and "$14.50" in b["razon"]
    assert d["intereses_mes_total"] == 1682 and d["pagos_minimos_total"] == 2162


def test_rn19_msi_no_entran_pero_se_cuentan(client, h, perfil_t26):
    d = client.get(URL, headers=h).json()
    msi = [x for x in d["sin_ranking"] if x["motivo"] == "MSI"]
    assert [(x["nombre"], x["saldo"], x["pago_mensual"]) for x in msi] == [
        ("MSI 1", 8000.0, 1000.0), ("MSI 2", 3000.0, 1000.0)]
    assert d["msi_mes_total"] == 2000 and "$2,000.00 de tus MSI" in d["resumen"]


def test_bola_de_nieve_daria_otro_orden(client, h, perfil_t26):
    bn = client.get(URL, headers=h).json()["bola_de_nieve"]
    assert bn["coincide"] is False and bn["mas_chica_nombre"] == "Tarjeta B"
    assert bn["diferencia_por_mil"] == 14.5


def test_estructura_de_respuesta(client, h, perfil_t26):
    """Formato publicado para T44 y T45: si cambia, avisarles."""
    d = client.get(URL, headers=h).json()
    assert set(d) == {"estado", "periodo", "ranking", "sin_ranking", "resumen",
                      "intereses_mes_total", "pagos_minimos_total", "msi_mes_total",
                      "bola_de_nieve", "supuestos"}
    assert set(d["ranking"][0]) == {"posicion", "clave", "tipo", "id", "nombre", "saldo",
                                    "tasa_anual", "tasa_mensual", "costo_anual_compuesto",
                                    "interes_mes", "utilizacion", "pago_minimo", "ahorro_por_mil",
                                    "accion", "razon", "comparacion", "avisos"}
    assert set(d["sin_ranking"][0]) == {"clave", "tipo", "id", "nombre", "saldo", "pago_mensual",
                                        "motivo", "mensaje"}


# --------------------------------------------- tarjetas y deudas juntas
def test_rn18_ordena_por_costo_y_no_por_lo_que_se_debe(client, h):
    post(client, h, "deudas", deuda("Hipoteca", 900000, 11, pago=9000, tipo="credito_hipotecario"))
    post(client, h, "tarjetas", tarjeta("Departamental", 3000, 5000, 90))
    post(client, h, "deudas", deuda("Auto", 120000, 12, pago=4500, tipo="credito_auto"))
    d = client.get(URL, headers=h).json()
    assert [x["nombre"] for x in d["ranking"]] == ["Departamental", "Auto", "Hipoteca"]
    assert [x["tipo"] for x in d["ranking"]] == ["tarjeta", "deuda", "deuda"]
    assert d["ranking"][1]["interes_mes"] == 1200 and d["ranking"][1]["pago_minimo"] == 4500


# ------------------------------------------------------------ casos borde
def test_sin_deudas(client, h):
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "sin_deudas" and d["ranking"] == [] and d["sin_ranking"] == []
    assert d["bola_de_nieve"] is None and d["intereses_mes_total"] == 0
    assert d["resumen"] == "No tienes deudas que te cobren intereses."


def test_una_sola_deuda(client, h):
    post(client, h, "tarjetas", tarjeta("Única", 8000, 20000, 50))
    d = client.get(URL, headers=h).json()
    assert len(d["ranking"]) == 1 and "única deuda" in d["ranking"][0]["razon"]
    assert d["bola_de_nieve"] is None


def test_deuda_liquidada_no_aparece(client, h):
    post(client, h, "deudas", deuda("Ya pagada", 0, 20))
    viva = post(client, h, "deudas", deuda("Préstamo", 30000, 24, pago=2000))
    d = client.get(URL, headers=h).json()
    assert [x["id"] for x in d["ranking"]] == [viva["id"]]
    client.put(f"/api/v1/deudas/{viva['id']}", json={"saldo_actual": 0}, headers=h)    # se liquida
    assert client.get(URL, headers=h).json()["estado"] == "sin_deudas"


def test_tarjeta_con_limite_en_cero(client, h):
    post(client, h, "tarjetas", tarjeta("Sin límite", 4000, 0, 50))
    x = client.get(URL, headers=h).json()["ranking"][0]
    assert x["utilizacion"] is None and x["interes_mes"] > 0
    assert [a["codigo"] for a in x["avisos"]] == ["LIMITE_CERO"]


def test_tarjetas_que_no_cuestan_quedan_fuera(client, h):
    post(client, h, "tarjetas", tarjeta("Al corriente", 0, 30000, 50))
    post(client, h, "tarjetas", tarjeta("Sin tasa", 5000, 30000, None))
    post(client, h, "deudas", deuda("Familiar", 10000, 0, pago=1000, tipo="familiar_amigo"))
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "sin_deudas"
    assert sorted(x["motivo"] for x in d["sin_ranking"]) == ["SIN_INTERESES", "SIN_SALDO",
                                                             "SIN_TASA"]


def test_tarjeta_inactiva_no_se_ordena(client, h, perfil_t26):
    _, b = perfil_t26
    client.put(f"/api/v1/tarjetas/{b['id']}", json={"activa": False}, headers=h)
    d = client.get(URL, headers=h).json()
    assert [x["nombre"] for x in d["ranking"]] == ["Tarjeta A"]


# ------------------------------------------------------- acceso y lectura
def test_cada_usuario_ve_solo_sus_deudas(client, h, h2, perfil_t26):
    assert len(client.get(URL, headers=h).json()["ranking"]) == 2
    assert client.get(URL, headers=h2).json()["estado"] == "sin_deudas"


def test_get_no_modifica_datos(client, h, perfil_t26):
    antes = (contar(Tarjeta), contar(Deuda), contar(ScoreHistorial))
    client.get(URL, headers=h)
    assert (contar(Tarjeta), contar(Deuda), contar(ScoreHistorial)) == antes