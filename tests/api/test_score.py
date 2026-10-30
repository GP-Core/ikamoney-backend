"""GET /api/v1/score y /api/v1/score/historial (T35). "Hoy" es el 15 de marzo de 2026."""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import ScoreHistorial
from app.services import fechas
from tests.conftest import TestSession

URL = "/api/v1/score"
HIST = "/api/v1/score/historial"


def ingreso(monto=20000):
    return {"tipo": "ingreso", "concepto": "Sueldo", "monto": monto, "frecuencia": "mensual",
            "fecha": "2026-01-01"}


def gasto(cat, monto, clase, fecha="2026-01-01"):
    return {"tipo": "gasto", "concepto": "Gasto", "monto": monto, "categoria_id": cat,
            "clase": clase, "fecha": fecha, "frecuencia": "mensual" if clase == "fijo" else "unico"}


def tarjeta(nombre, saldo, limite, tasa):
    return {"nombre": nombre, "banco": "Banco", "limite_credito": limite, "saldo_actual": saldo,
            "dia_corte": 10, "dia_pago": 30, "tasa_anual": tasa}


def post(client, h, ruta, cuerpo):
    r = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def filas_historial() -> int:
    with TestSession() as db:
        return db.scalar(select(func.count()).select_from(ScoreHistorial))


@pytest.fixture
def perfil_t26(client, h, cat):
    """Perfil de ejemplo de T25 / T26 capturado por la API."""
    post(client, h, "movimientos", ingreso())
    post(client, h, "movimientos", gasto(cat, 8000, "fijo"))
    for fecha in ("2025-12-10", "2026-01-10", "2026-02-10"):
        post(client, h, "movimientos", gasto(cat, 4000, "variable", fecha))
    a = post(client, h, "tarjetas", tarjeta("Tarjeta A", 20000, 60000, 60))
    b = post(client, h, "tarjetas", tarjeta("Tarjeta B", 12000, 30000, 45))
    post(client, h, "msi", {"tarjeta_id": a["id"], "descripcion": "MSI 1", "monto_original": 12000,
                            "num_mensualidades": 12, "mensualidades_pagadas": 4,
                            "fecha_compra": "2025-11-10"})
    post(client, h, "msi", {"tarjeta_id": b["id"], "descripcion": "MSI 2", "monto_original": 6000,
                            "num_mensualidades": 6, "mensualidades_pagadas": 3,
                            "fecha_compra": "2025-12-10"})
    return a, b


# ------------------------------------------------------------- acceso
@pytest.mark.parametrize("ruta", [URL, HIST])
def test_sin_token_401(client, ruta):
    r = client.get(ruta)
    assert r.status_code == 401 and r.json()["codigo"] == "NO_AUTENTICADO"


# ------------------------------------------------------- datos faltantes
def test_usuario_nuevo_no_tiene_score(client, h):
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "datos_faltantes"
    assert d["puntaje"] is None and d["nivel"] is None and d["factores"] == []
    assert [(f["dato"], f["obligatorio"]) for f in d["faltantes"]] == [("ingresos", True),
                                                                       ("gastos", False)]
    assert d["periodo"] == "2026-03" and d["version_modelo"]
    assert client.get(HIST, headers=h).json()["puntos"] == []


def test_sin_ingresos_no_tiene_score(client, h):
    post(client, h, "tarjetas", tarjeta("Tarjeta A", 20000, 60000, 60))
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "datos_faltantes" and d["faltantes"][0]["dato"] == "ingresos"
    assert filas_historial() == 0                       # sin score no se guarda historial


def test_sin_gastos_calcula_y_avisa(client, h):
    post(client, h, "movimientos", ingreso())
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "calculado" and d["puntaje"] is not None
    assert d["faltantes"] == [{"dato": "gastos", "obligatorio": False,
                               "mensaje": d["faltantes"][0]["mensaje"]}]


# ---------------------------------------------------- perfil de T25 / T26
def test_perfil_t26_coincide_con_t25(client, h, perfil_t26):
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "calculado"
    assert d["puntaje"] == 78 and d["puntaje_bruto"] == 77.5            # CP-09
    assert d["nivel"] == "en_revision" and d["nivel_texto"] == "En revisión"
    assert d["tope_aplicado"] is False and d["motivo_tope"] is None
    f = {x["clave"]: x for x in d["factores"]}
    esperado = {  # valor, subpuntaje, aporte, puntos perdidos (tabla de T25)
        "relacion_deuda_ingreso": (20.81, 100.0, 30.0, 0.0),
        "utilizacion_credito": (47.78, 44.44, 11.11, 13.89),
        "flujo_libre": (19.19, 97.57, 24.39, 0.61),
        "carga_msi": (10.0, 100.0, 10.0, 0.0),
        "comportamiento_pago": (None, 20.0, 2.0, 8.0),
    }
    for clave, (valor, sub, aporte, perdidos) in esperado.items():
        assert (f[clave]["valor"], f[clave]["subpuntaje"], f[clave]["aporte"],
                f[clave]["puntos_perdidos"]) == (valor, sub, aporte, perdidos), clave
    assert f["comportamiento_pago"]["categoria"] == "solo_minimo"
    assert d["orden_mejora"] == ["utilizacion_credito", "comportamiento_pago", "flujo_libre"]
    assert d["faltantes"] == []


def test_pesos_configurados_suman_100(client, h, perfil_t26):
    factores = client.get(URL, headers=h).json()["factores"]
    assert [f["peso"] for f in factores] == [30, 25, 25, 10, 10]
    assert sum(f["peso"] for f in factores) == 100
    assert all(f["justificacion_peso"] and f["explicacion"] and f["como_mejorar"] for f in factores)


def test_estructura_de_respuesta(client, h, perfil_t26):
    """Contrato publicado para T34, T37 y T38: si cambia, avisarles."""
    d = client.get(URL, headers=h).json()
    assert set(d) == {"estado", "puntaje", "puntaje_bruto", "nivel", "nivel_texto",
                      "tope_aplicado", "motivo_tope", "periodo", "version_modelo", "factores",
                      "orden_mejora", "faltantes", "supuestos"}
    assert set(d["factores"][0]) == {"clave", "nombre", "formula", "disponible", "peso",
                                     "peso_efectivo", "valor", "categoria", "subpuntaje", "aporte",
                                     "puntos_perdidos", "explicacion", "como_mejorar",
                                     "justificacion_peso", "datos"}
    h_ = client.get(HIST, headers=h).json()
    assert set(h_) == {"meses", "puntos"}
    assert set(h_["puntos"][0]) == {"periodo", "puntaje", "nivel", "nivel_texto",
                                    "calculado_en", "version_modelo"}


# ----------------------------------------------------- casos especiales
def test_sin_tarjetas_se_omite_utilizacion(client, h, cat):
    post(client, h, "movimientos", ingreso())
    post(client, h, "movimientos", gasto(cat, 8000, "fijo"))
    d = client.get(URL, headers=h).json()
    util = next(f for f in d["factores"] if f["clave"] == "utilizacion_credito")
    assert util["disponible"] is False and util["valor"] is None and util["aporte"] == 0
    assert round(sum(f["peso_efectivo"] for f in d["factores"]), 2) == 100
    assert any("No tienes tarjetas" in s for s in d["supuestos"])


def test_flujo_negativo_aplica_tope_59(client, h, cat):
    post(client, h, "movimientos", ingreso(10000))
    post(client, h, "movimientos", gasto(cat, 10100, "fijo"))       # flujo −1 %
    d = client.get(URL, headers=h).json()
    assert d["puntaje_bruto"] > 59                                   # 68.67 sin tope
    assert d["puntaje"] == 59 and d["nivel"] == "en_riesgo"
    assert d["tope_aplicado"] is True and d["motivo_tope"] == "flujo_negativo"


# ----------------------------------------------- recálculo (T17) e historial
def test_cada_alta_cambio_y_baja_recalcula(client, h, cat):
    post(client, h, "movimientos", ingreso())                       # alta
    assert filas_historial() == 1
    t = post(client, h, "tarjetas", tarjeta("Tarjeta A", 20000, 60000, 60))   # alta
    assert filas_historial() == 2
    client.put(f"/api/v1/tarjetas/{t['id']}", json={"saldo_actual": 50000}, headers=h)  # cambio
    assert filas_historial() == 3
    actual = client.get(URL, headers=h).json()["puntaje"]
    assert client.get(HIST, headers=h).json()["puntos"][-1]["puntaje"] == actual
    client.delete(f"/api/v1/tarjetas/{t['id']}", headers=h)                    # baja
    assert filas_historial() == 4
    assert client.get(HIST, headers=h).json()["puntos"][-1]["puntaje"] == \
        client.get(URL, headers=h).json()["puntaje"]


def test_sin_cambio_en_el_score_no_duplica(client, h):
    post(client, h, "movimientos", ingreso())
    t = post(client, h, "tarjetas", tarjeta("Tarjeta A", 20000, 60000, 60))
    antes = filas_historial()
    r = client.put(f"/api/v1/tarjetas/{t['id']}", json={"nombre": "Otra"}, headers=h)
    assert r.status_code == 200                                      # recalcula, pero el score
    assert filas_historial() == antes                                # no cambió: no hay fila nueva


def test_get_score_no_escribe(client, h, perfil_t26):
    antes = filas_historial()
    client.get(URL, headers=h)
    client.get(HIST, headers=h)
    assert filas_historial() == antes


def test_historial_por_mes(client, h, perfil_t26, monkeypatch):
    marzo = client.get(URL, headers=h).json()["puntaje"]
    monkeypatch.setattr(fechas, "hoy_mx", lambda: date(2026, 4, 10))
    a, _ = perfil_t26
    client.put(f"/api/v1/tarjetas/{a['id']}", json={"saldo_actual": 5000}, headers=h)
    abril = client.get(URL, headers=h).json()["puntaje"]
    puntos = client.get(HIST, headers=h).json()["puntos"]
    assert [(p["periodo"], p["puntaje"]) for p in puntos] == [("2026-03", marzo), ("2026-04", abril)]
    assert abril > marzo                                              # bajó la utilización
    solo_abril = client.get(HIST, params={"meses": 1}, headers=h).json()
    assert solo_abril["meses"] == 1 and [p["periodo"] for p in solo_abril["puntos"]] == ["2026-04"]


@pytest.mark.parametrize("meses", [0, 25, "doce"])
def test_historial_parametro_invalido_422(client, h, meses):
    r = client.get(HIST, params={"meses": meses}, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "DATOS_INVALIDOS"


def test_cada_usuario_ve_solo_su_score(client, h, h2, perfil_t26):
    assert client.get(URL, headers=h).json()["puntaje"] == 78
    otro = client.get(URL, headers=h2).json()
    assert otro["estado"] == "datos_faltantes"
    assert client.get(HIST, headers=h2).json()["puntos"] == []