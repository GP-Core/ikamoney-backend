"""GET /api/v1/proyeccion: balance del mes y proyección (T33). "Hoy" es el 15 de marzo de 2026."""
import pytest

from tests.conftest import DEUDA

URL = "/api/v1/proyeccion"

# Tabla de T25: mes, flujo y acumulado del perfil de ejemplo
TABLA_T25 = [(1, 3838.00, 8838.00), (2, 3870.43, 12708.43), (3, 3902.37, 16610.80),
             (4, 4933.84, 21544.64), (5, 4964.83, 26509.47), (6, 4995.36, 31504.83),
             (7, 5025.43, 36530.26), (8, 5055.05, 41585.30), (9, 6084.22, 47669.52),
             (10, 6112.96, 53782.48), (11, 6141.26, 59923.74), (12, 6169.14, 66092.89)]


def ingreso(monto=20000, frecuencia="mensual", fecha="2026-01-01"):
    return {"tipo": "ingreso", "concepto": "Sueldo", "monto": monto,
            "frecuencia": frecuencia, "fecha": fecha}


def gasto(cat, monto, clase, fecha, frecuencia=None):
    return {"tipo": "gasto", "concepto": "Gasto", "monto": monto, "categoria_id": cat,
            "clase": clase, "fecha": fecha,
            "frecuencia": frecuencia or ("mensual" if clase == "fijo" else "unico")}


def tarjeta(nombre, saldo, limite, tasa):
    return {"nombre": nombre, "banco": "Banco", "limite_credito": limite, "saldo_actual": saldo,
            "dia_corte": 10, "dia_pago": 30, "tasa_anual": tasa}


def post(client, h, ruta, cuerpo):
    r = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def perfil_t26(client, h, cat):
    """Perfil de ejemplo de T25 / T26 capturado por la API."""
    post(client, h, "movimientos", ingreso())
    post(client, h, "movimientos", gasto(cat, 8000, "fijo", "2026-01-01"))
    for fecha in ("2025-12-10", "2026-01-10", "2026-02-10"):     # promedio de 3 meses = 4,000
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


def test_sin_token_401(client):
    r = client.get(URL)
    assert r.status_code == 401 and r.json()["codigo"] == "NO_AUTENTICADO"


def test_usuario_recien_registrado(client, h):
    r = client.get(URL, headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["estado"] == "sin_datos" and d["avisos"][0]["codigo"] == "SIN_DATOS"
    assert d["balance_mes"] is None and d["proyeccion"] == [] and d["resumen"] is None
    assert d["mes_inicio"] == "2026-03" and d["meses"] == 12


def test_perfil_t26_balance_del_mes(client, h, perfil_t26):
    d = client.get(URL, params={"ahorro_inicial": 5000}, headers=h).json()
    assert d["estado"] == "completo" and d["avisos"] == []
    b = d["balance_mes"]
    assert b["mes"] == 1 and b["periodo"] == "2026-03"
    assert (b["ingresos"], b["gastos_fijos"], b["gastos_variables"]) == (20000, 8000, 4000)
    assert (b["pagos_tarjetas"], b["mensualidades_msi"], b["otras_cuotas"]) == (2162, 2000, 0)
    assert b["compromisos"] == 4162
    assert b["flujo"] == 3838 and b["acumulado"] == 8838          # CP-05
    assert [t["pago"] for t in b["tarjetas"]] == [1460, 702]
    assert [t["interes"] for t in b["tarjetas"]] == [1160, 522]
    s = d["supuestos"]
    assert s["base_gastos_variables"] == "promedio_3_meses" and s["gastos_variables_estimados"] == 4000


def test_perfil_t26_proyeccion_igual_a_la_tabla(client, h, perfil_t26):
    d = client.get(URL, params={"ahorro_inicial": 5000}, headers=h).json()
    assert len(d["proyeccion"]) == 12
    for (mes, flujo, acumulado), m in zip(TABLA_T25, d["proyeccion"]):
        assert m["mes"] == mes
        assert m["flujo"] == flujo and m["acumulado"] == acumulado, f"mes {mes}"
    assert d["proyeccion"][3]["msi_activos"] == 1 and d["proyeccion"][8]["msi_activos"] == 0
    assert d["proyeccion"][11]["periodo"] == "2027-02"
    r = d["resumen"]
    assert r["flujo_minimo"] == 3838 and r["mes_flujo_minimo"] == 1
    assert r["acumulado_minimo"] == 8838 and r["meses_en_negativo"] == 0
    assert r["saldo_tarjetas_final"] == 26692.22                     # 16,682.64 + 10,009.58


def test_horizonte_configurable(client, h, perfil_t26):
    assert len(client.get(URL, params={"meses": 6}, headers=h).json()["proyeccion"]) == 6
    assert len(client.get(URL, params={"meses": 24}, headers=h).json()["proyeccion"]) == 24


@pytest.mark.parametrize("params", [{"meses": 2}, {"meses": 25}, {"meses": "doce"},
                                    {"ahorro_inicial": -1}, {"ahorro_inicial": "1.234"}])
def test_parametros_invalidos_422(client, h, params):
    r = client.get(URL, params=params, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "DATOS_INVALIDOS"


def test_sin_ingresos(client, h):
    post(client, h, "tarjetas", tarjeta("Tarjeta A", 20000, 60000, 60))
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "sin_ingresos"
    codigos = [a["codigo"] for a in d["avisos"]]
    assert "SIN_INGRESOS" in codigos and "SALDO_NEGATIVO" in codigos
    assert d["balance_mes"]["flujo"] == -1460 and d["resumen"]["meses_en_negativo"] == 12


def test_sin_deudas(client, h, cat):
    post(client, h, "movimientos", ingreso())
    post(client, h, "movimientos", gasto(cat, 8000, "fijo", "2026-01-01"))
    d = client.get(URL, headers=h).json()
    assert d["estado"] == "completo"
    assert all(m["compromisos"] == 0 and m["flujo"] == 12000 for m in d["proyeccion"])
    assert d["resumen"]["saldo_tarjetas_final"] == 0


def test_cada_usuario_ve_solo_su_proyeccion(client, h, h2, perfil_t26):
    assert client.get(URL, headers=h).json()["estado"] == "completo"
    otro = client.get(URL, headers=h2).json()
    assert otro["estado"] == "sin_datos" and otro["proyeccion"] == []


def test_recurrentes_se_cuentan_cada_vez_que_caen(client, h):
    post(client, h, "movimientos", ingreso(monto=5000, frecuencia="quincenal"))
    assert client.get(URL, headers=h).json()["balance_mes"]["ingresos"] == 10000


def test_ingreso_unico_solo_en_su_mes(client, h):
    post(client, h, "movimientos", ingreso(monto=3000, frecuencia="unico", fecha="2026-05-20"))
    meses = client.get(URL, headers=h).json()["proyeccion"]
    assert [m["ingresos"] for m in meses[:4]] == [0, 0, 3000, 0]


def test_ingreso_con_fecha_fin(client, h):
    cuerpo = {**ingreso(), "fecha_fin": "2026-06-30"}
    post(client, h, "movimientos", cuerpo)
    meses = client.get(URL, headers=h).json()["proyeccion"]
    assert [m["ingresos"] for m in meses[:5]] == [20000, 20000, 20000, 20000, 0]


def test_gasto_variable_del_mes_mayor_al_promedio(client, h, cat):
    for fecha in ("2026-01-10", "2026-02-10"):
        post(client, h, "movimientos", gasto(cat, 4000, "variable", fecha))
    post(client, h, "movimientos", gasto(cat, 6000, "variable", "2026-03-05"))
    meses = client.get(URL, headers=h).json()["proyeccion"]
    assert meses[0]["gastos_variables"] == 6000 and meses[1]["gastos_variables"] == 4000


def test_gasto_variable_sin_historial_usa_lo_registrado(client, h, cat):
    post(client, h, "movimientos", gasto(cat, 2500, "variable", "2026-03-05"))
    d = client.get(URL, headers=h).json()
    assert d["supuestos"]["base_gastos_variables"] == "registrado"
    assert all(m["gastos_variables"] == 2500 for m in d["proyeccion"])


def test_otras_deudas_se_descuentan(client, h):
    post(client, h, "movimientos", ingreso())
    post(client, h, "deudas", DEUDA)                       # pago mensual de 4,500
    b = client.get(URL, headers=h).json()["balance_mes"]
    assert b["otras_cuotas"] == 4500 and b["flujo"] == 15500


def test_tarjeta_sin_tasa_avisa(client, h):
    post(client, h, "movimientos", ingreso())
    sin_tasa = {k: v for k, v in tarjeta("Sin tasa", 10000, 50000, 0).items() if k != "tasa_anual"}
    post(client, h, "tarjetas", sin_tasa)
    d = client.get(URL, headers=h).json()
    assert "TARJETA_SIN_TASA" in [a["codigo"] for a in d["avisos"]]
    assert d["balance_mes"]["tarjetas"][0]["interes"] == 0


def test_msi_cancelado_y_tarjeta_inactiva_no_cuentan(client, h, perfil_t26):
    a, b = perfil_t26
    plan_b = client.get("/api/v1/msi", params={"tarjeta_id": b["id"]}, headers=h).json()[0]
    client.put(f"/api/v1/msi/{plan_b['id']}", json={"estatus": "cancelado"}, headers=h)
    client.put(f"/api/v1/tarjetas/{a['id']}", json={"activa": False}, headers=h)
    m = client.get(URL, headers=h).json()["balance_mes"]
    assert m["mensualidades_msi"] == 1000                   # sigue el MSI 1 de la tarjeta A
    assert [t["nombre"] for t in m["tarjetas"]] == ["Tarjeta B"]


def test_solo_lectura_no_modifica_datos(client, h, perfil_t26):
    antes = client.get("/api/v1/tarjetas", headers=h).json()
    client.get(URL, headers=h)
    assert client.get("/api/v1/tarjetas", headers=h).json() == antes