"""POST /api/v1/simulador/calcular (T40): validación, escenarios por omisión, errores y filtrado
por usuario. El cálculo en sí (T41) se prueba en test_simulador.py; aquí se comprueba que el
endpoint lo entregue completo y que traduzca los casos de error. \"Hoy\" es el 15-mar-2026."""
import pytest

from app.models import PlanMsi, ScoreHistorial, Tarjeta
from tests.api.test_simulador import contar, ingreso, msi, perfil_t26, post  # noqa: F401
from tests.api.test_simulador import tarjeta as nueva_tarjeta

URL = "/api/v1/simulador/calcular"


def pedir(client, h, escenarios=None, precio=9000, prioridad="media", ahorro=5000, **extra):
    cuerpo = {"descripcion": "Laptop", "precio": precio, "prioridad": prioridad,
              "ahorro_inicial": ahorro, **extra}
    if escenarios is not None:
        cuerpo["escenarios"] = escenarios
    return client.post(URL, json=cuerpo, headers=h)


def por_id(respuesta):
    return {e["id"]: e for e in respuesta["escenarios"]}


# ------------------------------------------------------------------ respuesta correcta
def test_cp10_por_la_api(client, h, perfil_t26):
    a, _ = perfil_t26
    r = pedir(client, h, [{"tipo": "contado"}, msi(a["id"], 12)])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["estado"] == "calculado" and d["periodo"] == "2026-03" and d["meses"] == 12
    assert d["score_actual"]["puntaje"] == 78
    contado, doce = por_id(d)["contado"], por_id(d)[f"msi-{a['id']}-12"]
    assert (contado["veredicto"], contado["regla"]) == ("no_recomendable", "RN-15")
    assert doce["score"]["puntaje"] == 70 and doce["score"]["cambio"] == -8
    assert doce["veredicto"] == "recomendable"
    assert d["menor_impacto"] == doce["id"] and doce["menor_impacto"] and not contado["menor_impacto"]
    assert d["veredicto"] == "recomendable"


def test_escenario_que_no_alcanza_es_200_con_motivo(client, h, perfil_t26):
    a, _ = perfil_t26
    r = pedir(client, h, [{"tipo": "contado"}, msi(a["id"], 12)], precio=100000)
    assert r.status_code == 200
    e = por_id(r.json())[f"msi-{a['id']}-12"]
    assert e["aplica"] is False and e["motivo"]["codigo"] == "LIMITE_INSUFICIENTE"
    assert e["balance"] == [] and e["score"] is None and e["veredicto"] is None


def test_plazo_fuera_de_rango_es_200_con_motivo(client, h, perfil_t26):
    a, _ = perfil_t26
    r = pedir(client, h, [msi(a["id"], 1), msi(a["id"], 100), msi(a["id"], 6)])
    assert r.status_code == 200
    e = por_id(r.json())
    assert e[f"msi-{a['id']}-1"]["motivo"]["codigo"] == "PLAZO_NO_VALIDO"
    assert e[f"msi-{a['id']}-100"]["motivo"]["codigo"] == "PLAZO_NO_VALIDO"
    assert e[f"msi-{a['id']}-6"]["aplica"]


def test_tarjeta_inactiva_es_200_con_motivo(client, h, perfil_t26):
    a, b = perfil_t26
    client.put(f"/api/v1/tarjetas/{b['id']}", json={"activa": False}, headers=h)
    r = pedir(client, h, [msi(b["id"], 6), msi(a["id"], 6)])
    assert r.status_code == 200
    e = por_id(r.json())
    assert e[f"msi-{b['id']}-6"]["motivo"]["codigo"] == "TARJETA_NO_DISPONIBLE"
    assert e[f"msi-{a['id']}-6"]["aplica"]


# ------------------------------------------------------- escenarios por omisión
def test_sin_escenarios_evalua_contado_y_4_plazos_con_la_tarjeta_de_mas_credito(client, h,
                                                                                  perfil_t26):
    a, _ = perfil_t26          # A tiene 40,000 de crédito disponible y B 18,000
    r = pedir(client, h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert [e["id"] for e in d["escenarios"]] == [
        "contado", *(f"msi-{a['id']}-{m}" for m in (3, 6, 12, 18))]
    e = por_id(d)
    assert [x["score"]["puntaje"] for x in d["escenarios"]] == [53, 45, 64, 70, 71]
    assert e[f"msi-{a['id']}-3"]["veredicto"] == "con_precaucion"
    assert d["menor_impacto"] == f"msi-{a['id']}-18" and d["veredicto"] == "recomendable"


def test_lista_vacia_es_lo_mismo_que_omitirla(client, h, perfil_t26):
    vacia = pedir(client, h, []).json()
    omitida = pedir(client, h).json()
    assert [e["id"] for e in vacia["escenarios"]] == [e["id"] for e in omitida["escenarios"]]


def test_sin_tarjetas_por_omision_solo_contado(client, h):
    post(client, h, "movimientos", ingreso())
    d = pedir(client, h).json()
    assert [e["id"] for e in d["escenarios"]] == ["contado"]


# -------------------------------------------------------------------------- errores
def test_sin_ingresos_400(client, h):
    r = pedir(client, h, [{"tipo": "contado"}])
    assert r.status_code == 400
    d = r.json()
    assert d["codigo"] == "SIN_INGRESOS" and d["campos"][0]["campo"] == "ingresos"


def test_sin_ingresos_tambien_por_omision(client, h):
    assert pedir(client, h).json()["codigo"] == "SIN_INGRESOS"


def test_tarjeta_inexistente_404(client, h, perfil_t26):
    r = pedir(client, h, [{"tipo": "contado"}, msi(99999, 6)])
    assert r.status_code == 404
    d = r.json()
    assert d["codigo"] == "TARJETA_NO_ENCONTRADA"
    assert d["campos"][0]["campo"] == "escenarios.1.tarjeta_id"


def test_tarjeta_de_otro_usuario_404(client, h, h2, perfil_t26):
    ajena = post(client, h2, "tarjetas", nueva_tarjeta("Ajena", 0, 50000, 40))
    r = pedir(client, h, [msi(ajena["id"], 6)])
    assert r.status_code == 404 and r.json()["codigo"] == "TARJETA_NO_ENCONTRADA"


@pytest.mark.parametrize("cambio, campo", [
    ({"precio": 0}, "precio"),
    ({"precio": -5}, "precio"),
    ({"precio": 100.123}, "precio"),
    ({"prioridad": "urgente"}, "prioridad"),
    ({"descripcion": ""}, "descripcion"),
    ({"descripcion": "x" * 121}, "descripcion"),
    ({"ahorro_inicial": -1}, "ahorro_inicial"),
    ({"usuario_id": 2}, "usuario_id"),
    ({"escenarios": [{"tipo": "efectivo"}]}, "escenarios.0.tipo"),
    ({"escenarios": [{"tipo": "msi", "tarjeta_id": 1}]}, "escenarios.0"),
    ({"escenarios": [{"tipo": "msi", "meses": 6}]}, "escenarios.0"),
    ({"escenarios": [{"tipo": "contado", "meses": 6}]}, "escenarios.0"),
    ({"escenarios": [{"tipo": "contado"}] * 7}, "escenarios"),
])
def test_datos_invalidos_422(client, h, perfil_t26, cambio, campo):
    cuerpo = {"descripcion": "Laptop", "precio": 9000, "prioridad": "media",
              "escenarios": [{"tipo": "contado"}], **cambio}
    r = client.post(URL, json=cuerpo, headers=h)
    assert r.status_code == 422, r.text
    assert campo in [c["campo"] for c in r.json()["campos"]]


def test_faltan_campos_obligatorios_422(client, h):
    r = client.post(URL, json={}, headers=h)
    assert r.status_code == 422
    assert {"descripcion", "precio", "prioridad"} <= {c["campo"] for c in r.json()["campos"]}


def test_sin_token_401(client):
    r = client.post(URL, json={"descripcion": "x", "precio": 1, "prioridad": "alta"})
    assert r.status_code == 401 and r.json()["codigo"] == "NO_AUTENTICADO"


# ------------------------------------------------------- usuario y datos guardados
def test_usa_los_datos_del_usuario_del_token(client, h, h2, perfil_t26):
    post(client, h2, "movimientos", ingreso(50000))
    uno = pedir(client, h, [{"tipo": "contado"}], precio=1000).json()
    dos = pedir(client, h2, [{"tipo": "contado"}], precio=1000).json()
    assert uno["escenarios"][0]["balance"][0]["ingresos"] == 20000
    assert dos["escenarios"][0]["balance"][0]["ingresos"] == 50000


def test_no_guarda_nada(client, h, perfil_t26):
    a, _ = perfil_t26
    antes = [contar(m) for m in (Tarjeta, PlanMsi, ScoreHistorial)]
    assert pedir(client, h, [{"tipo": "contado"}, msi(a["id"], 12)]).status_code == 200
    assert pedir(client, h).status_code == 200
    assert [contar(m) for m in (Tarjeta, PlanMsi, ScoreHistorial)] == antes
