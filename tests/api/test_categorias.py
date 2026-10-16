import pytest

URL = "/api/v1/categorias"


def test_requiere_token(client):
    assert client.get(URL).status_code == 401


def test_listar_base_y_propias_sin_ajenas(client, h, h2, cat):
    client.post(URL, json={"nombre": "Mascotas"}, headers=h)
    client.post(URL, json={"nombre": "Gimnasio"}, headers=h2)
    uno = client.get(URL, headers=h).json()
    assert [(c["nombre"], c["base"]) for c in uno] == [("Vivienda", True), ("Mascotas", False)]
    dos = client.get(URL, headers=h2).json()
    assert [c["nombre"] for c in dos] == ["Vivienda", "Gimnasio"]


def test_crear(client, h):
    r = client.post(URL, json={"nombre": "  Mascotas  "}, headers=h)   # se recortan los espacios
    assert r.status_code == 201
    assert r.json()["nombre"] == "Mascotas" and r.json()["base"] is False


def test_duplicados(client, h, h2, cat):
    r = client.post(URL, json={"nombre": "vivienda"}, headers=h)       # choca con la base
    assert r.status_code == 400 and r.json()["codigo"] == "CATEGORIA_DUPLICADA"
    client.post(URL, json={"nombre": "Mascotas"}, headers=h)
    assert client.post(URL, json={"nombre": "MASCOTAS"}, headers=h).status_code == 400
    assert client.post(URL, json={"nombre": "Mascotas"}, headers=h2).status_code == 201  # otro usuario, sí


@pytest.mark.parametrize("cuerpo", [{"nombre": ""}, {"nombre": "x" * 61}, {"nombre": "A", "base": True}, {}])
def test_validaciones_422(client, h, cuerpo):
    assert client.post(URL, json=cuerpo, headers=h).status_code == 422
