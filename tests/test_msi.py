import pytest

from tests.conftest import TestSession
from app.models import Categoria
from tests.conftest import TARJETA

URL = "/api/v1/msi"


def plan(tarjeta_id, **extra):
    return {"tarjeta_id": tarjeta_id, "descripcion": "iPhone", "monto_original": 12000,
            "num_mensualidades": 12, "fecha_compra": "2026-01-10", **extra}


def test_crear_calcula_mensualidad_y_derivados(client, h, tarjeta):
    r = client.post(URL, json=plan(tarjeta["id"], mensualidades_pagadas=2), headers=h)
    assert r.status_code == 201
    p = r.json()
    assert p["monto_mensualidad"] == 1000
    assert p["mensualidades_restantes"] == 10 and p["saldo_pendiente"] == 10000
    assert p["estatus"] == "activo" and p["origen"] == "manual" and p["tarjeta_id"] == tarjeta["id"]


def test_mensualidad_con_redondeo(client, h, tarjeta):
    p = client.post(URL, json=plan(tarjeta["id"], monto_original=1000), headers=h).json()
    assert p["monto_mensualidad"] == 83.33   # 1000 / 12; 83.33 × 12 = 999.96, dentro de la tolerancia


def test_mensualidad_explicita_coherente(client, h, tarjeta):
    r = client.post(URL, json=plan(tarjeta["id"], monto_mensualidad=1000), headers=h)
    assert r.status_code == 201


def test_mensualidad_incoherente_422(client, h, tarjeta):
    r = client.post(URL, json=plan(tarjeta["id"], monto_mensualidad=900), headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "MSI_MONTOS_INCOHERENTES"


@pytest.mark.parametrize("cambio,codigo", [
    ({"num_mensualidades": 1}, "DATOS_INVALIDOS"),
    ({"num_mensualidades": 61}, "DATOS_INVALIDOS"),
    ({"monto_original": 0}, "MONTO_INVALIDO"),
    ({"monto_original": -5}, "MONTO_INVALIDO"),
    ({"monto_mensualidad": 0}, "MONTO_INVALIDO"),
    ({"mensualidades_pagadas": -1}, "DATOS_INVALIDOS"),
    ({"mensualidades_pagadas": 13}, "MSI_PAGADAS_EXCEDEN"),
    ({"fecha_compra": "2026-03-16"}, "FECHA_INVALIDA"),   # hoy fijo = 15-mar-2026
    ({"fecha_compra": "10-01-2026"}, "DATOS_INVALIDOS"),
    ({"descripcion": ""}, "DATOS_INVALIDOS"),
    ({"estatus": "activo"}, "DATOS_INVALIDOS"),           # estatus no se manda al crear
    ({"origen": "extraido"}, "DATOS_INVALIDOS"),          # el origen lo pone el servidor
])
def test_validaciones_422(client, h, tarjeta, cambio, codigo):
    r = client.post(URL, json=plan(tarjeta["id"], **cambio), headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["codigo"] == codigo


def test_todas_pagadas_nace_liquidado(client, h, tarjeta):
    p = client.post(URL, json=plan(tarjeta["id"], mensualidades_pagadas=12), headers=h).json()
    assert p["estatus"] == "liquidado" and p["mensualidades_restantes"] == 0 and p["saldo_pendiente"] == 0


def test_tarjeta_ajena_o_inexistente_404(client, h, h2, tarjeta):
    r = client.post(URL, json=plan(tarjeta["id"]), headers=h2)
    assert r.status_code == 404 and r.json()["codigo"] == "TARJETA_NO_ENCONTRADA"
    assert client.post(URL, json=plan(9999), headers=h).status_code == 404


def test_tarjeta_inactiva_400(client, h):
    t = client.post("/api/v1/tarjetas", json={**TARJETA, "activa": False}, headers=h).json()
    r = client.post(URL, json=plan(t["id"]), headers=h)
    assert r.status_code == 400 and r.json()["codigo"] == "TARJETA_INACTIVA"


def test_categoria(client, h, h2, tarjeta, usuario1):
    with TestSession() as db:
        base = Categoria(usuario_id=None, nombre="Compras")
        propia = Categoria(usuario_id=usuario1[0], nombre="Tecnología")
        db.add_all([base, propia])
        db.commit()
        id_base, id_propia = base.id, propia.id
    assert client.post(URL, json=plan(tarjeta["id"], categoria_id=id_base), headers=h).status_code == 201
    assert client.post(URL, json=plan(tarjeta["id"], categoria_id=id_propia), headers=h).status_code == 201
    # otro usuario no puede usar la categoría propia de este (y tampoco la tarjeta)
    t2 = client.post("/api/v1/tarjetas", json=TARJETA, headers=h2).json()
    r = client.post(URL, json=plan(t2["id"], categoria_id=id_propia), headers=h2)
    assert r.status_code == 404 and r.json()["codigo"] == "CATEGORIA_NO_ENCONTRADA"


def test_actualizar_pagadas_hasta_liquidar_y_reactivar(client, h, tarjeta):
    id_ = client.post(URL, json=plan(tarjeta["id"]), headers=h).json()["id"]
    p = client.put(f"{URL}/{id_}", json={"mensualidades_pagadas": 5}, headers=h).json()
    assert p["mensualidades_restantes"] == 7 and p["saldo_pendiente"] == 7000 and p["estatus"] == "activo"
    p = client.put(f"{URL}/{id_}", json={"mensualidades_pagadas": 12}, headers=h).json()
    assert p["estatus"] == "liquidado" and p["saldo_pendiente"] == 0
    p = client.put(f"{URL}/{id_}", json={"mensualidades_pagadas": 11}, headers=h).json()
    assert p["estatus"] == "activo" and p["mensualidades_restantes"] == 1


def test_editar_pagadas_mayor_al_total_422(client, h, tarjeta):
    id_ = client.post(URL, json=plan(tarjeta["id"]), headers=h).json()["id"]
    r = client.put(f"{URL}/{id_}", json={"mensualidades_pagadas": 13}, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "MSI_PAGADAS_EXCEDEN"
    # bajar el total por debajo de lo ya pagado también lo detecta
    client.put(f"{URL}/{id_}", json={"mensualidades_pagadas": 6}, headers=h)
    r = client.put(f"{URL}/{id_}", json={"num_mensualidades": 4}, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "MSI_PAGADAS_EXCEDEN"


def test_cambiar_monto_o_meses_recalcula_mensualidad(client, h, tarjeta):
    id_ = client.post(URL, json=plan(tarjeta["id"]), headers=h).json()["id"]
    p = client.put(f"{URL}/{id_}", json={"monto_original": 6000}, headers=h).json()
    assert p["monto_mensualidad"] == 500
    p = client.put(f"{URL}/{id_}", json={"num_mensualidades": 6}, headers=h).json()
    assert p["monto_mensualidad"] == 1000
    r = client.put(f"{URL}/{id_}", json={"monto_mensualidad": 1}, headers=h)   # no cuadra
    assert r.status_code == 422 and r.json()["codigo"] == "MSI_MONTOS_INCOHERENTES"


def test_cancelar_y_no_se_reactiva_solo(client, h, tarjeta):
    id_ = client.post(URL, json=plan(tarjeta["id"]), headers=h).json()["id"]
    assert client.put(f"{URL}/{id_}", json={"estatus": "cancelado"}, headers=h).json()["estatus"] == "cancelado"
    assert client.put(f"{URL}/{id_}", json={"mensualidades_pagadas": 3}, headers=h).json()["estatus"] == "cancelado"
    assert client.put(f"{URL}/{id_}", json={"estatus": "activo"}, headers=h).json()["estatus"] == "activo"
    assert client.put(f"{URL}/{id_}", json={"estatus": "liquidado"}, headers=h).status_code == 422


def test_mover_a_otra_tarjeta(client, h, h2, tarjeta):
    id_ = client.post(URL, json=plan(tarjeta["id"]), headers=h).json()["id"]
    t2 = client.post("/api/v1/tarjetas", json={**TARJETA, "nombre": "Nu"}, headers=h).json()
    assert client.put(f"{URL}/{id_}", json={"tarjeta_id": t2["id"]}, headers=h).json()["tarjeta_id"] == t2["id"]
    ajena = client.post("/api/v1/tarjetas", json=TARJETA, headers=h2).json()
    assert client.put(f"{URL}/{id_}", json={"tarjeta_id": ajena["id"]}, headers=h).status_code == 404


def test_listar_y_filtros(client, h, tarjeta):
    t2 = client.post("/api/v1/tarjetas", json={**TARJETA, "nombre": "Nu"}, headers=h).json()
    client.post(URL, json=plan(tarjeta["id"], descripcion="A"), headers=h)
    client.post(URL, json=plan(t2["id"], descripcion="B", mensualidades_pagadas=12), headers=h)
    assert len(client.get(URL, headers=h).json()) == 2
    assert [p["descripcion"] for p in client.get(URL, params={"tarjeta_id": t2["id"]}, headers=h).json()] == ["B"]
    assert [p["descripcion"] for p in client.get(URL, params={"estatus": "activo"}, headers=h).json()] == ["A"]


def test_aislamiento_entre_usuarios(client, h, h2, tarjeta):
    id_ = client.post(URL, json=plan(tarjeta["id"]), headers=h).json()["id"]
    assert client.get(URL, headers=h2).json() == []
    for metodo, kw in [("get", {}), ("put", {"json": {"descripcion": "x"}}), ("delete", {})]:
        r = getattr(client, metodo)(f"{URL}/{id_}", headers=h2, **kw)
        assert r.status_code == 404 and r.json()["codigo"] == "MSI_NO_ENCONTRADO"


def test_eliminar(client, h, tarjeta):
    id_ = client.post(URL, json=plan(tarjeta["id"]), headers=h).json()["id"]
    r = client.delete(f"{URL}/{id_}", headers=h)
    assert r.status_code == 200 and r.json() == {"id": id_, "eliminado": True}
    assert client.get(f"{URL}/{id_}", headers=h).status_code == 404
