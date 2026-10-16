import pytest
from tests.conftest import TestSession
from app.models import EstadoCuenta
from tests.conftest import TARJETA
from datetime import date

URL = "/api/v1/tarjetas"


def test_requiere_token(client):
    r = client.get(URL)
    assert r.status_code == 401 and r.json()["codigo"] == "NO_AUTENTICADO"
    r = client.get(URL, headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401 and r.json()["codigo"] == "TOKEN_INVALIDO"


def test_crear_devuelve_campos_derivados(client, h):
    r = client.post(URL, json=TARJETA, headers=h)
    assert r.status_code == 201
    t = r.json()
    assert t["porcentaje_limite_usado"] == 25.0
    assert t["credito_disponible"] == 15000.0
    assert t["proxima_fecha_corte"] == "2026-04-10"   # hoy = 15-mar; el corte del 10 ya pasó
    assert t["proxima_fecha_pago"] == "2026-03-30"
    assert t["ultimos_4"] == "1234" and t["activa"] is True


def test_saldo_por_defecto_cero(client, h):
    body = {k: v for k, v in TARJETA.items() if k != "saldo_actual"}
    t = client.post(URL, json=body, headers=h).json()
    assert t["saldo_actual"] == 0 and t["porcentaje_limite_usado"] == 0


def test_dia_31_usa_ultimo_dia_del_mes(client, h, monkeypatch):
    from app.services import fechas
    from datetime import date
    monkeypatch.setattr(fechas, "hoy_mx", lambda: date(2026, 2, 1))
    t = client.post(URL, json={**TARJETA, "dia_pago": 31, "dia_corte": 31}, headers=h).json()
    assert t["proxima_fecha_pago"] == "2026-02-28" and t["proxima_fecha_corte"] == "2026-02-28"


def test_estado_de_cuenta_manda_sobre_la_regla(client, h, tarjeta):
    with TestSession() as db:
        db.add(EstadoCuenta(tarjeta_id=tarjeta["id"], periodo_inicio=date(2026, 2, 11),
                            fecha_corte=date(2026, 3, 10), fecha_limite_pago=date(2026, 3, 25),
                            saldo_al_corte=5000, estatus="revisado"))
        db.commit()
    assert client.get(f"{URL}/{tarjeta['id']}", headers=h).json()["proxima_fecha_pago"] == "2026-03-25"


@pytest.mark.parametrize("cambio,campo", [
    ({"limite_credito": -1}, "limite_credito"),
    ({"saldo_actual": -5}, "saldo_actual"),
    ({"dia_corte": 0}, "dia_corte"),
    ({"dia_corte": 32}, "dia_corte"),
    ({"dia_pago": 40}, "dia_pago"),
    ({"ultimos_4": "123"}, "ultimos_4"),
    ({"ultimos_4": "4111111111111111"}, "ultimos_4"),   # jamás el número completo
    ({"ultimos_4": "12ab"}, "ultimos_4"),
    ({"tasa_anual": 1000}, "tasa_anual"),
    ({"tasa_anual": -1}, "tasa_anual"),
    ({"limite_credito": 100.123}, "limite_credito"),    # más de 2 decimales
    ({"nombre": "   "}, "nombre"),
    ({"nombre": "x" * 61}, "nombre"),
    ({"cvv": "123"}, "cvv"),                            # campos desconocidos
])
def test_validaciones_422(client, h, cambio, campo):
    r = client.post(URL, json={**TARJETA, **cambio}, headers=h)
    assert r.status_code == 422
    cuerpo = r.json()
    assert set(cuerpo) == {"codigo", "mensaje", "campos"}
    assert campo in [c["campo"] for c in cuerpo["campos"]]


def test_falta_campo_obligatorio(client, h):
    body = {k: v for k, v in TARJETA.items() if k != "banco"}
    r = client.post(URL, json=body, headers=h)
    assert r.status_code == 422 and r.json()["campos"][0]["campo"] == "banco"


def test_limite_negativo_codigo_monto_invalido(client, h):
    r = client.post(URL, json={**TARJETA, "limite_credito": -1}, headers=h)
    assert r.json()["codigo"] == "MONTO_INVALIDO"


def test_listar_solo_propias_y_filtro(client, h, h2, tarjeta):
    client.post(URL, json={**TARJETA, "nombre": "Otra", "activa": False}, headers=h)
    client.post(URL, json={**TARJETA, "nombre": "Ajena"}, headers=h2)
    assert [t["nombre"] for t in client.get(URL, headers=h).json()] == ["BBVA Azul", "Otra"]
    assert [t["nombre"] for t in client.get(URL, params={"activa": True}, headers=h).json()] == ["BBVA Azul"]


def test_editar_parcial(client, h, tarjeta):
    r = client.put(f"{URL}/{tarjeta['id']}", json={"saldo_actual": 10000, "dia_pago": 28}, headers=h)
    assert r.status_code == 200
    t = r.json()
    assert t["saldo_actual"] == 10000 and t["porcentaje_limite_usado"] == 50.0
    assert t["dia_pago"] == 28 and t["nombre"] == "BBVA Azul"   # lo demás no cambió


def test_editar_limpiar_tasa_y_rechazar_nulos(client, h, tarjeta):
    assert client.put(f"{URL}/{tarjeta['id']}", json={"tasa_anual": None}, headers=h).json()["tasa_anual"] is None
    assert client.put(f"{URL}/{tarjeta['id']}", json={"nombre": None}, headers=h).status_code == 422
    assert client.put(f"{URL}/{tarjeta['id']}", json={}, headers=h).status_code == 422


def test_no_se_puede_cambiar_el_dueno(client, h, tarjeta):
    assert client.put(f"{URL}/{tarjeta['id']}", json={"usuario_id": 99}, headers=h).status_code == 422


def test_otro_usuario_recibe_404(client, h, h2, tarjeta):
    for metodo, kw in [("get", {}), ("put", {"json": {"nombre": "x"}}), ("delete", {})]:
        r = getattr(client, metodo)(f"{URL}/{tarjeta['id']}", headers=h2, **kw)
        assert r.status_code == 404 and r.json()["codigo"] == "TARJETA_NO_ENCONTRADA"
    assert client.get(f"{URL}/9999", headers=h).status_code == 404


def test_eliminar_borra_msi_en_cascada(client, h, tarjeta):
    for i in range(2):
        r = client.post("/api/v1/msi", headers=h, json={
            "tarjeta_id": tarjeta["id"], "descripcion": f"Compra {i}", "monto_original": 1200,
            "num_mensualidades": 12, "fecha_compra": "2026-01-10"})
        assert r.status_code == 201
    r = client.delete(f"{URL}/{tarjeta['id']}", headers=h)
    assert r.status_code == 200 and r.json() == {"id": tarjeta["id"], "eliminado": True, "planes_msi_eliminados": 2}
    assert client.get("/api/v1/msi", headers=h).json() == []
    assert client.get(f"{URL}/{tarjeta['id']}", headers=h).status_code == 404
