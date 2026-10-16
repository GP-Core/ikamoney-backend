import pytest

from tests.conftest import DEUDA

URL = "/api/v1/deudas"


def test_crear_y_proxima_fecha(client, h):
    r = client.post(URL, json=DEUDA, headers=h)
    assert r.status_code == 201
    d = r.json()
    assert d["estatus"] == "activa" and d["saldo_actual"] == 120000
    assert d["proxima_fecha_pago"] == "2026-04-05"   # hoy = 15-mar, día de pago = 5


def test_minimos_y_opcionales(client, h):
    r = client.post(URL, json={"nombre": "Con mi primo", "tipo": "familiar_amigo",
                               "monto_original": 3000, "saldo_actual": 3000}, headers=h)
    assert r.status_code == 201
    assert r.json()["proxima_fecha_pago"] is None and r.json()["acreedor"] is None


def test_saldo_cero_nace_liquidada(client, h):
    d = client.post(URL, json={**DEUDA, "saldo_actual": 0}, headers=h).json()
    assert d["estatus"] == "liquidada" and d["proxima_fecha_pago"] is None


@pytest.mark.parametrize("cambio", [
    {"monto_original": 0}, {"monto_original": -10}, {"saldo_actual": -1},
    {"tipo": "tarjeta"}, {"tasa_anual": 1000}, {"pago_mensual": 0}, {"dia_pago": 0},
    {"dia_pago": 32}, {"fecha_inicio": "15/01/2025"}, {"nombre": ""}, {"nombre": "x" * 101},
])
def test_validaciones_422(client, h, cambio):
    r = client.post(URL, json={**DEUDA, **cambio}, headers=h)
    assert r.status_code == 422 and set(r.json()) == {"codigo", "mensaje", "campos"}


def test_monto_cero_usa_codigo_de_t17(client, h):
    r = client.post(URL, json={**DEUDA, "monto_original": 0}, headers=h)
    assert r.json()["codigo"] == "MONTO_INVALIDO"
    assert r.json()["mensaje"] == "El monto debe ser mayor a cero."


def test_pagar_y_reactivar(client, h):
    id_ = client.post(URL, json=DEUDA, headers=h).json()["id"]
    d = client.put(f"{URL}/{id_}", json={"saldo_actual": 0}, headers=h).json()
    assert d["estatus"] == "liquidada" and d["proxima_fecha_pago"] is None
    d = client.put(f"{URL}/{id_}", json={"saldo_actual": 500}, headers=h).json()
    assert d["estatus"] == "activa" and d["proxima_fecha_pago"] == "2026-04-05"


def test_filtro_por_estatus(client, h):
    client.post(URL, json=DEUDA, headers=h)
    client.post(URL, json={**DEUDA, "nombre": "Saldada", "saldo_actual": 0}, headers=h)
    assert [d["nombre"] for d in client.get(URL, params={"estatus": "liquidada"}, headers=h).json()] == ["Saldada"]
    assert len(client.get(URL, headers=h).json()) == 2
    assert client.get(URL, params={"estatus": "x"}, headers=h).status_code == 422


def test_aislamiento_entre_usuarios(client, h, h2):
    id_ = client.post(URL, json=DEUDA, headers=h).json()["id"]
    assert client.get(URL, headers=h2).json() == []
    for metodo, kw in [("get", {}), ("put", {"json": {"nombre": "x"}}), ("delete", {})]:
        r = getattr(client, metodo)(f"{URL}/{id_}", headers=h2, **kw)
        assert r.status_code == 404 and r.json()["codigo"] == "DEUDA_NO_ENCONTRADA"


def test_eliminar(client, h):
    id_ = client.post(URL, json=DEUDA, headers=h).json()["id"]
    r = client.delete(f"{URL}/{id_}", headers=h)
    assert r.status_code == 200 and r.json() == {"id": id_, "eliminado": True}
    assert client.get(f"{URL}/{id_}", headers=h).status_code == 404
