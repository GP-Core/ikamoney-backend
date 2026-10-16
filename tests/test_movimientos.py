from datetime import date

import pytest

from app.services import fechas

URL = "/api/v1/movimientos"


def ingreso(**kw):
    return {"tipo": "ingreso", "concepto": "Nómina", "monto": 15000,
            "frecuencia": "quincenal", "fecha": "2026-01-01", **kw}


def gasto(cat, **kw):
    return {"tipo": "gasto", "concepto": "Renta", "monto": 8000, "frecuencia": "mensual",
            "fecha": "2026-01-05", "clase": "fijo", "categoria_id": cat, **kw}


def variable(cat, **kw):
    datos = {"concepto": "Cena", "clase": "variable", "frecuencia": "unico",
             "fecha": "2026-03-20", "monto": 500, **kw}
    return gasto(cat, **datos)


def test_requiere_token(client):
    assert client.get(URL).status_code == 401


def test_crear_ingreso(client, h):
    r = client.post(URL, json=ingreso(), headers=h)
    assert r.status_code == 201
    d = r.json()
    assert d["id"].startswith("ingreso-") and d["clase"] is None and d["categoria"] is None
    assert d["monto"] == 15000 and d["frecuencia"] == "quincenal"


def test_crear_gasto_fijo_y_variable(client, h, cat):
    f = client.post(URL, json=gasto(cat), headers=h).json()
    assert f["id"].startswith("gasto-") and f["clase"] == "fijo" and f["categoria"] == "Vivienda"
    v = client.post(URL, json=variable(cat), headers=h)
    assert v.status_code == 201 and v.json()["clase"] == "variable"


@pytest.mark.parametrize("cambio,codigo", [
    ({"clase": "variable"}, "VARIABLE_DEBE_SER_UNICO"),     # variable con frecuencia mensual
    ({"frecuencia": "unico"}, "FIJO_NO_PUEDE_SER_UNICO"),
    ({"clase": None}, "CLASE_REQUERIDA"),
    ({"categoria_id": None}, "CATEGORIA_REQUERIDA"),
    ({"fecha_fin": "2025-12-31"}, "FECHA_FIN_INVALIDA"),
    ({"monto": 0}, "MONTO_INVALIDO"),
    ({"monto": -1}, "MONTO_INVALIDO"),
    ({"monto": 10.123}, "DATOS_INVALIDOS"),
    ({"concepto": ""}, "DATOS_INVALIDOS"),
    ({"frecuencia": "anual"}, "DATOS_INVALIDOS"),
    ({"tipo": "otro"}, "DATOS_INVALIDOS"),
    ({"fecha": "15/03/2026"}, "DATOS_INVALIDOS"),
    ({"usuario_id": 1}, "DATOS_INVALIDOS"),
])
def test_validaciones_gasto(client, h, cat, cambio, codigo):
    r = client.post(URL, json=gasto(cat, **cambio), headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["codigo"] == codigo
    assert set(r.json()) == {"codigo", "mensaje", "campos"}


def test_ingreso_no_lleva_clase_ni_categoria(client, h, cat):
    for extra in ({"clase": "fijo"}, {"categoria_id": cat}):
        r = client.post(URL, json=ingreso(**extra), headers=h)
        assert r.status_code == 422 and r.json()["codigo"] == "CAMPO_NO_APLICA"


def test_categoria_inexistente_o_ajena_404(client, h, h2):
    ajena = client.post("/api/v1/categorias", json={"nombre": "Mascotas"}, headers=h2).json()["id"]
    for cid in (ajena, 9999):
        r = client.post(URL, json=gasto(cid), headers=h)
        assert r.status_code == 404 and r.json()["codigo"] == "CATEGORIA_NO_ENCONTRADA"


def test_listar_mes_con_recurrentes_y_totales(client, h, cat):
    client.post(URL, json=ingreso(), headers=h)                       # quincenal: días 1 y 16
    client.post(URL, json=ingreso(concepto="Freelance", frecuencia="mensual", monto=3000,
                                  fecha="2026-01-10", fecha_fin="2026-02-28"), headers=h)  # ya terminó
    client.post(URL, json=gasto(cat), headers=h)                      # renta, día 5
    client.post(URL, json=variable(cat), headers=h)                   # 20-mar
    client.post(URL, json=variable(cat, fecha="2026-04-02", monto=999), headers=h)  # abril
    r = client.get(URL, params={"mes": "2026-03"}, headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["mes"] == "2026-03"
    assert d["totales"] == {"ingresos": 30000.0, "gastos": 8500.0, "gastos_fijos": 8000.0,
                            "gastos_variables": 500.0, "balance": 21500.0}
    assert [m["fecha_ocurrencia"] for m in d["movimientos"]] == [
        "2026-03-01", "2026-03-05", "2026-03-16", "2026-03-20"]
    # sin parámetro usa el mes actual (hoy fijo = 15-mar-2026)
    assert client.get(URL, headers=h).json()["mes"] == "2026-03"
    # febrero sí incluye el freelance
    feb = client.get(URL, params={"mes": "2026-02"}, headers=h).json()
    assert len(feb["movimientos"]) == 4


def test_filtros(client, h, cat):
    client.post(URL, json=ingreso(), headers=h)
    client.post(URL, json=gasto(cat), headers=h)
    client.post(URL, json=variable(cat), headers=h)

    def q(**p):
        return client.get(URL, params={"mes": "2026-03", **p}, headers=h).json()["movimientos"]

    assert len(q(tipo="ingreso")) == 2
    assert len(q(tipo="gasto")) == 2
    assert {m["tipo"] for m in q(categoria_id=cat)} == {"gasto"}   # por categoría solo hay gastos
    assert client.get(URL, params={"mes": "2026-13"}, headers=h).status_code == 422
    assert client.get(URL, params={"mes": "2026-3"}, headers=h).status_code == 422
    assert client.get(URL, params={"tipo": "x"}, headers=h).status_code == 422


def test_inactivo_no_aparece(client, h):
    id_ = client.post(URL, json=ingreso(), headers=h).json()["id"]
    assert client.put(f"{URL}/{id_}", json={"activo": False}, headers=h).json()["activo"] is False
    assert client.get(URL, params={"mes": "2026-03"}, headers=h).json()["movimientos"] == []


def test_editar_parcial(client, h, cat):
    id_ = client.post(URL, json=gasto(cat), headers=h).json()["id"]
    r = client.put(f"{URL}/{id_}", json={"monto": 8500}, headers=h)
    assert r.status_code == 200
    assert r.json()["monto"] == 8500 and r.json()["concepto"] == "Renta"


def test_editar_fijo_a_variable_exige_frecuencia_unica(client, h, cat):
    id_ = client.post(URL, json=gasto(cat), headers=h).json()["id"]
    r = client.put(f"{URL}/{id_}", json={"clase": "variable"}, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "VARIABLE_DEBE_SER_UNICO"
    r = client.put(f"{URL}/{id_}", json={"clase": "variable", "frecuencia": "unico"}, headers=h)
    assert r.status_code == 200 and r.json()["clase"] == "variable"


def test_editar_rechazos(client, h, cat):
    id_ = client.post(URL, json=gasto(cat), headers=h).json()["id"]
    assert client.put(f"{URL}/{id_}", json={}, headers=h).status_code == 422
    assert client.put(f"{URL}/{id_}", json={"tipo": "ingreso"}, headers=h).status_code == 422
    assert client.put(f"{URL}/{id_}", json={"monto": 0}, headers=h).json()["codigo"] == "MONTO_INVALIDO"
    assert client.put(f"{URL}/{id_}", json={"concepto": None}, headers=h).status_code == 422
    assert client.put(f"{URL}/{id_}", json={"categoria_id": 9999}, headers=h).status_code == 404


def test_eliminar_y_404(client, h, cat):
    id_ = client.post(URL, json=gasto(cat), headers=h).json()["id"]
    r = client.delete(f"{URL}/{id_}", headers=h)
    assert r.status_code == 200 and r.json() == {"id": id_, "eliminado": True}
    assert client.delete(f"{URL}/{id_}", headers=h).status_code == 404
    assert client.put(f"{URL}/abc", json={"monto": 1}, headers=h).status_code == 404
    assert client.delete(f"{URL}/gasto-9999", headers=h).status_code == 404


def test_aislamiento_entre_usuarios(client, h, h2, cat):
    id_ = client.post(URL, json=gasto(cat), headers=h).json()["id"]
    assert client.get(URL, params={"mes": "2026-03"}, headers=h2).json()["movimientos"] == []
    for metodo, kw in [("put", {"json": {"monto": 1}}), ("delete", {})]:
        r = getattr(client, metodo)(f"{URL}/{id_}", headers=h2, **kw)
        assert r.status_code == 404 and r.json()["codigo"] == "MOVIMIENTO_NO_ENCONTRADO"


def test_ocurrencias_en_mes():
    f = fechas.ocurrencias_en_mes
    assert f("semanal", date(2026, 3, 2), None, 2026, 3) == [date(2026, 3, d) for d in (2, 9, 16, 23, 30)]
    assert f("mensual", date(2026, 1, 31), None, 2026, 2) == [date(2026, 2, 28)]   # día 31 en mes corto
    assert f("quincenal", date(2026, 1, 31), None, 2026, 3) == [date(2026, 3, 1), date(2026, 3, 16)]
    assert f("unico", date(2026, 3, 20), None, 2026, 4) == []
    assert f("mensual", date(2026, 3, 10), date(2026, 3, 31), 2026, 4) == []         # ya terminó
    assert f("mensual", date(2026, 3, 20), None, 2026, 2) == []                      # aún no empieza
