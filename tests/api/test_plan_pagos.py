"""Plan de pagos en GET /api/v1/priorizador?extra_mensual=... (T45). "Hoy" es el 15 de marzo
de 2026. Es el mismo endpoint de T43: la T45 completa su respuesta con la sección `plan`."""
import pytest

URL = "/api/v1/priorizador"


def post(client, h, ruta, cuerpo):
    r = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def tarjeta(nombre, saldo, limite, tasa):
    return {"nombre": nombre, "banco": "Banco", "limite_credito": limite, "saldo_actual": saldo,
            "dia_corte": 10, "dia_pago": 30, "tasa_anual": tasa}


def gasto(cat, monto, clase, fecha="2026-01-01"):
    return {"tipo": "gasto", "concepto": "Gasto", "monto": monto, "categoria_id": cat,
            "clase": clase, "fecha": fecha, "frecuencia": "mensual" if clase == "fijo" else "unico"}


def tarjetas_t26(client, h):
    a = post(client, h, "tarjetas", tarjeta("Tarjeta A", 20000, 60000, 60))
    b = post(client, h, "tarjetas", tarjeta("Tarjeta B", 12000, 30000, 45))
    post(client, h, "msi", {"tarjeta_id": a["id"], "descripcion": "MSI 1", "monto_original": 12000,
                            "num_mensualidades": 12, "mensualidades_pagadas": 4,
                            "fecha_compra": "2025-11-10"})
    post(client, h, "msi", {"tarjeta_id": b["id"], "descripcion": "MSI 2", "monto_original": 6000,
                            "num_mensualidades": 6, "mensualidades_pagadas": 3,
                            "fecha_compra": "2025-12-10"})


@pytest.fixture
def perfil_t26(client, h, cat):
    """Perfil completo de T25 / T26: ingreso, gastos, tarjetas A y B y sus MSI."""
    post(client, h, "movimientos", {"tipo": "ingreso", "concepto": "Sueldo", "monto": 20000,
                                    "frecuencia": "mensual", "fecha": "2026-01-01"})
    post(client, h, "movimientos", gasto(cat, 8000, "fijo"))
    for fecha in ("2025-12-10", "2026-01-10", "2026-02-10"):
        post(client, h, "movimientos", gasto(cat, 4000, "variable", fecha))
    tarjetas_t26(client, h)


def plan(client, h, extra=None):
    params = {} if extra is None else {"extra_mensual": extra}
    r = client.get(URL, params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["plan"]


# ------------------------------------------------------ CP-12 (T25 / T26)
def test_cp12_por_la_api(client, h, perfil_t26):
    p = plan(client, h, 3000)
    t = p["total"]
    assert (t["meses_plan"], t["liquidacion_plan"], t["intereses_plan"]) == (8, "2026-10", 7338.1)
    assert (t["meses_base"], t["liquidacion_base"], t["intereses_base"]) == (74, "2032-04",
                                                                             70170.38)
    assert t["ahorro"] == 62832.28 and t["meses_menos"] == 66
    assert [(d["nombre"], d["meses_plan"], d["liquidacion_plan"]) for d in p["deudas"]] == [
        ("Tarjeta A", 6, "2026-08"), ("Tarjeta B", 8, "2026-10")]
    assert p["presupuesto_mensual"] == 5162 and p["extra_sugerido"] == 3800
    assert p["avisos"] == [] and "te ahorras $62,832.28" in p["mensaje"]


def test_calendario_mes_a_mes(client, h, perfil_t26):
    cal = plan(client, h, 3000)["calendario"]
    assert len(cal) == 8 and cal[0]["periodo"] == "2026-03" and cal[-1]["periodo"] == "2026-10"
    assert cal[0]["pagos"][0] == {"clave": cal[0]["pagos"][0]["clave"], "pago": 4460.0,
                                  "abono_extra": 3000.0, "saldo_final": 16700.0}
    assert cal[0]["pagos"][1]["abono_extra"] == 0                     # RN-20: B paga el mínimo
    assert cal[-1]["saldo_total"] == 0


def test_estructura_del_plan(client, h, perfil_t26):
    """Formato publicado para T46: si cambia, avisar."""
    p = plan(client, h, 500)
    assert set(p) == {"extra_mensual", "extra_sugerido", "presupuesto_mensual", "escenario_base",
                      "escenario_base_texto", "deudas", "total", "calendario",
                      "calendario_completo", "mensaje", "avisos", "supuestos"}
    assert set(p["deudas"][0]) == {"clave", "nombre", "posicion", "meses_plan", "liquidacion_plan",
                                   "intereses_plan", "meses_base", "liquidacion_base",
                                   "intereses_base"}
    assert set(p["total"]) == {"meses_plan", "liquidacion_plan", "intereses_plan", "meses_base",
                               "liquidacion_base", "intereses_base", "ahorro", "meses_menos"}
    assert set(p["calendario"][0]) == {"mes", "periodo", "pagos", "total_pagado", "intereses",
                                       "saldo_total"}
    assert p["escenario_base"] == "solo_minimo" and p["escenario_base_texto"]
    assert any("compras nuevas" in s for s in p["supuestos"])


# ------------------------------------------------------------ extra_mensual
@pytest.mark.parametrize("extra,meses,ahorro", [(None, 29, 39746.69), (0, 29, 39746.69),
                                                (500, 20, 51232.62), (3000, 8, 62832.28)])
def test_extra_mensual(client, h, perfil_t26, extra, meses, ahorro):
    p = plan(client, h, extra)
    assert p["extra_mensual"] == (extra or 0)
    assert (p["total"]["meses_plan"], p["total"]["ahorro"]) == (meses, ahorro)


def test_ce09_extra_mayor_a_lo_que_sobra(client, h, perfil_t26):
    p = plan(client, h, 5000)                                        # le sobran 3,838 al mes
    assert [a["codigo"] for a in p["avisos"]] == ["EXCEDENTE_NO_SOSTENIBLE"]
    assert p["total"]["meses_plan"] is not None


@pytest.mark.parametrize("extra", [-1, "mucho", "1.234"])
def test_extra_invalido_422(client, h, extra):
    r = client.get(URL, params={"extra_mensual": extra}, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "DATOS_INVALIDOS"


# ------------------------------------------------------------ casos borde
def test_sin_ingresos_avisa_que_no_hay_dinero_extra(client, h):
    tarjetas_t26(client, h)
    p = plan(client, h)
    assert [a["codigo"] for a in p["avisos"]] == ["SIN_DINERO_EXTRA"]
    assert p["extra_sugerido"] == 0 and p["total"]["meses_plan"] == 29


def test_sin_deudas_no_hay_plan(client, h):
    assert plan(client, h, 500) is None


def test_deuda_sin_pago_mensual_no_entra_al_plan(client, h, perfil_t26):
    post(client, h, "deudas", {"nombre": "Sin pago", "tipo": "otro", "monto_original": 5000,
                               "saldo_actual": 5000, "tasa_anual": 80})
    p = plan(client, h, 3000)
    assert "DEUDA_SIN_PAGO_MENSUAL" in [a["codigo"] for a in p["avisos"]]
    assert "Sin pago" not in [d["nombre"] for d in p["deudas"]]


def test_mismo_endpoint_que_el_ranking(client, h, perfil_t26):
    d = client.get(URL, params={"extra_mensual": 3000}, headers=h).json()
    assert [x["nombre"] for x in d["ranking"]] == ["Tarjeta A", "Tarjeta B"]
    assert [x["clave"] for x in d["plan"]["deudas"]] == [x["clave"] for x in d["ranking"]]