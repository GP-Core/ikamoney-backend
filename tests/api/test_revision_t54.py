"""Revisión de T54: autenticación en cada ruta, aislamiento entre usuarios, validación del lado del
servidor con entradas basura y errores que no filtran detalles internos.

Es una batería repetible: cubre sola las rutas que se agreguen después. Lo que se encontró y no se
corrigió está en docs/REVISION_T54.md.
"""
import json

import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from app.main import app
from tests.conftest import DEUDA, TARJETA

PROHIBIDO = ("Traceback", "sqlalchemy", "SQLAlchemy", "pymysql", "File \"", "mysql", "sqlite",
             "IntegrityError", "ProgrammingError", "pydantic")


def _sin_filtraciones(texto: str):
    for p in PROHIBIDO:
        assert p not in texto, f"la respuesta filtra {p!r}: {texto[:300]}"


def _forma_de_error(r):
    cuerpo = r.json()
    assert set(cuerpo) == {"codigo", "mensaje", "campos"}, cuerpo
    assert isinstance(cuerpo["campos"], list)
    _sin_filtraciones(r.text)


# ======================================================================= 1. autenticación
def _rutas_v1():
    for ruta in app.routes:
        if isinstance(ruta, APIRoute) and ruta.path.startswith("/api/v1"):
            for metodo in sorted(ruta.methods - {"HEAD", "OPTIONS"}):
                yield metodo, ruta.path


def _con_ids(path: str) -> str:
    import re
    return re.sub(r"\{[^}]+\}", "1", path)


RUTAS_V1 = list(_rutas_v1())


def test_la_revision_ve_las_rutas():
    assert len(RUTAS_V1) >= 30   # si baja, el barrido dejó de recorrer la aplicación


@pytest.mark.parametrize("metodo,path", RUTAS_V1, ids=[f"{m} {p}" for m, p in RUTAS_V1])
def test_toda_ruta_de_v1_pide_token(client, metodo, path):
    r = client.request(metodo, _con_ids(path))
    assert (r.status_code, r.json()["codigo"]) == (401, "NO_AUTENTICADO")
    r = client.request(metodo, _con_ids(path), headers={"Authorization": "Bearer basura"})
    assert (r.status_code, r.json()["codigo"]) == (401, "TOKEN_INVALIDO")
    _sin_filtraciones(r.text)


# ======================================================================= 2. aislamiento entre usuarios
@pytest.fixture
def datos_de_uno(client, h, cat):
    """Un recurso de cada tipo del usuario 1; devuelve la ruta de detalle de cada uno."""
    def crear(ruta, cuerpo):
        r = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=h)
        assert r.status_code == 201, r.text
        return r.json()

    tarjeta = crear("tarjetas", {**TARJETA, "saldo_actual": 15000})   # genera una alerta
    plan = crear("msi", {"tarjeta_id": tarjeta["id"], "descripcion": "Laptop", "monto_original": 12000,
                         "num_mensualidades": 12, "fecha_compra": "2026-01-10"})
    deuda = crear("deudas", DEUDA)
    propia = crear("categorias", {"nombre": "Mascotas"})
    ingreso = crear("movimientos", {"tipo": "ingreso", "concepto": "Sueldo", "monto": 20000,
                                    "frecuencia": "mensual", "fecha": "2026-03-01"})
    gasto = crear("movimientos", {"tipo": "gasto", "concepto": "Renta", "monto": 8000,
                                  "frecuencia": "mensual", "fecha": "2026-03-01",
                                  "categoria_id": cat, "clase": "fijo"})
    alerta = client.get("/api/v1/alertas", headers=h).json()["alertas"][0]
    return {"tarjetas": tarjeta["id"], "msi": plan["id"], "deudas": deuda["id"],
            "categorias": propia["id"], "movimientos": ingreso["id"], "gasto": gasto["id"],
            "alertas": alerta["id"]}


def test_otro_usuario_recibe_404_en_cada_recurso_ajeno(client, h2, datos_de_uno):
    d = datos_de_uno
    cuerpos = {"tarjetas": {"nombre": "X"}, "msi": {"descripcion": "X"}, "deudas": {"nombre": "X"},
               "categorias": {"nombre": "X"}, "movimientos": {"concepto": "X"},
               "alertas": {"leida": True}}
    for ruta, cuerpo in cuerpos.items():
        id_ = d[ruta]
        metodos = [("GET", None), ("PUT", cuerpo), ("DELETE", None)]
        if ruta == "alertas":
            metodos = [("PATCH", cuerpo)]
        for metodo, c in metodos:
            if ruta in ("categorias", "alertas", "movimientos") and metodo == "GET":
                continue   # sin detalle propio
            r = client.request(metodo, f"/api/v1/{ruta}/{id_}", json=c, headers=h2)
            assert r.status_code == 404, f"{metodo} /{ruta}/{id_}: {r.status_code} {r.text}"
            _forma_de_error(r)
    for metodo, c in (("PUT", {"concepto": "X"}), ("DELETE", None)):
        r = client.request(metodo, f"/api/v1/movimientos/{d['gasto']}", json=c, headers=h2)
        assert r.status_code == 404, r.text


def test_los_listados_del_otro_usuario_salen_vacios(client, h2, datos_de_uno):
    for ruta in ("tarjetas", "msi", "deudas"):
        assert client.get(f"/api/v1/{ruta}", headers=h2).json() == [], ruta
    assert client.get("/api/v1/alertas", headers=h2).json()["alertas"] == []
    mov = client.get("/api/v1/movimientos?mes=2026-03", headers=h2).json()
    assert mov["movimientos"] == [] and float(mov["totales"]["balance"]) == 0
    cats = client.get("/api/v1/categorias", headers=h2).json()
    assert all(c["nombre"] != "Mascotas" for c in cats)


def test_el_otro_usuario_no_puede_colgar_cosas_de_mis_recursos(client, h2, datos_de_uno, cat):
    d = datos_de_uno
    r = client.post("/api/v1/msi", headers=h2, json={
        "tarjeta_id": d["tarjetas"], "descripcion": "Intruso", "monto_original": 1200,
        "num_mensualidades": 12, "fecha_compra": "2026-01-10"})
    assert r.status_code in (404, 422), r.text
    r = client.post("/api/v1/movimientos", headers=h2, json={
        "tipo": "gasto", "concepto": "Intruso", "monto": 10, "fecha": "2026-03-01",
        "categoria_id": d["categorias"], "clase": "variable"})
    assert r.status_code in (404, 422), r.text            # categoría propia de otro usuario
    r = client.post("/api/v1/simulador/calcular", headers=h2, json={
        "descripcion": "x", "precio": 1000, "prioridad": "alta",
        "escenarios": [{"tipo": "msi", "tarjeta_id": d["tarjetas"], "meses": 12}]})
    assert r.status_code in (200, 404), r.text            # la tarjeta ajena no existe para este usuario
    if r.status_code == 200:
        assert r.json()["escenarios"][0]["aplica"] is False


def test_el_cuerpo_no_puede_cambiar_el_dueno(client, h, h2, tarjeta):
    r = client.post("/api/v1/tarjetas", json={**TARJETA, "usuario_id": 999}, headers=h)
    assert r.status_code == 422 and r.json()["campos"][0]["campo"] == "usuario_id"
    r = client.put(f"/api/v1/tarjetas/{tarjeta['id']}", json={"usuario_id": 2}, headers=h)
    assert r.status_code == 422


# ======================================================================= 3. validación en el servidor
VALIDO = {
    "tarjetas": ("POST", "/api/v1/tarjetas", TARJETA),
    "deudas": ("POST", "/api/v1/deudas", DEUDA),
    "ingreso": ("POST", "/api/v1/movimientos", {"tipo": "ingreso", "concepto": "Sueldo", "monto": 100,
                                                "frecuencia": "mensual", "fecha": "2026-03-01"}),
    "categorias": ("POST", "/api/v1/categorias", {"nombre": "Mascotas"}),
    "simulador": ("POST", "/api/v1/simulador/calcular", {"descripcion": "Laptop", "precio": 9000,
                                                         "prioridad": "media", "ahorro_inicial": 0}),
    "config": ("PUT", "/api/v1/alertas/configuracion", {"umbral_utilizacion": 70, "dias_anticipacion": 3}),
    "registro": ("POST", "/api/auth/registro", {"nombre": "Ana", "correo": "ana@ejemplo.com",
                                                "contrasena": "Clave1234", "acepta_terminos": True}),
}
# Valores crudos de JSON: algunos no se pueden construir con json.dumps (NaN, 1e400)
BASURA = ['-1', '0', '-0.01', '0.001', '1.005', 'NaN', 'Infinity', '-Infinity', '1e308', '1e400',
          '99999999999999999999999999', '"abc"', '""', '" "', 'null', 'true', '[]', '{}', '[1,2]',
          '"2026-02-30"', '"9999-99-99"', '"0000-00-00"', '"\\u0000"', '"' + 'x' * 10000 + '"',
          '"<script>alert(1)</script>"', '"\' OR 1=1 --"', '"💥"']


def _casos():
    for nombre, (metodo, path, base) in VALIDO.items():
        for campo in base:
            for i, crudo in enumerate(BASURA):
                yield pytest.param(metodo, path, base, campo, crudo, id=f"{nombre}.{campo}.{i}")


def _enviar(client, headers, metodo, path, base, campo, crudo):
    marcador = "__BASURA__"
    cuerpo = json.dumps({**base, campo: marcador}).replace(f'"{marcador}"', crudo)
    return client.request(metodo, path, content=cuerpo, headers={**headers, "content-type": "application/json"})


@pytest.mark.parametrize("metodo,path,base,campo,crudo", list(_casos()))
def test_ninguna_entrada_basura_provoca_un_500(client, h, metodo, path, base, campo, crudo):
    """Con cualquier valor raro en cualquier campo: nunca un 500 ni una fuga de detalles."""
    r = _enviar(client, h, metodo, path, base, campo, crudo)
    assert r.status_code < 500, f"{campo}={crudo[:40]}: {r.status_code} {r.text[:200]}"
    if r.status_code >= 400:
        _forma_de_error(r)


MUST_REJECT = [
    ("tarjetas", "limite_credito", '-1'), ("tarjetas", "saldo_actual", '-1'),
    ("tarjetas", "limite_credito", '0.001'), ("tarjetas", "saldo_actual", '1e308'),
    ("tarjetas", "saldo_actual", '"abc"'), ("tarjetas", "nombre", '""'),
    ("tarjetas", "nombre", '"' + 'x' * 10000 + '"'), ("tarjetas", "dia_corte", '32'),
    ("tarjetas", "dia_pago", '0'), ("tarjetas", "ultimos_4", '"12"'), ("tarjetas", "tasa_anual", '1000'),
    ("tarjetas", "tasa_anual", '-5'),
    ("deudas", "monto_original", '0'), ("deudas", "saldo_actual", '-1'), ("deudas", "pago_mensual", '-1'),
    ("deudas", "fecha_inicio", '"2026-02-30"'), ("deudas", "tipo", '"inventado"'),
    ("ingreso", "monto", '0'), ("ingreso", "monto", '-100'), ("ingreso", "monto", '"NaN"'),
    ("ingreso", "monto", '100.123'), ("ingreso", "concepto", '""'), ("ingreso", "fecha", '"2026-13-01"'),
    ("ingreso", "concepto", '"' + 'x' * 10000 + '"'),
    ("categorias", "nombre", '""'), ("categorias", "nombre", '"' + 'x' * 10000 + '"'),
    ("simulador", "precio", '0'), ("simulador", "precio", '-1'), ("simulador", "precio", '"abc"'),
    ("simulador", "prioridad", '"urgente"'), ("simulador", "ahorro_inicial", '-1'),
    ("config", "umbral_utilizacion", '0'), ("config", "dias_anticipacion", '99'),
    ("registro", "correo", '"no-es-correo"'), ("registro", "contrasena", '"corta1"'),
    ("registro", "contrasena", '"sololetrasaaa"'), ("registro", "nombre", '"A"'),
    ("registro", "acepta_terminos", '"si"'),
]


@pytest.mark.parametrize("recurso,campo,crudo", MUST_REJECT,
                         ids=[f"{r}.{c}.{v[:12]}" for r, c, v in MUST_REJECT])
def test_el_servidor_rechaza_lo_invalido_aunque_el_front_lo_deje_pasar(client, h, recurso, campo, crudo):
    metodo, path, base = VALIDO[recurso]
    r = _enviar(client, h, metodo, path, base, campo, crudo)
    assert 400 <= r.status_code < 500, f"{recurso}.{campo}={crudo[:30]} se aceptó ({r.status_code})"
    _forma_de_error(r)


def test_montos_negativos_dan_el_codigo_de_monto(client, h):
    r = _enviar(client, h, *VALIDO["ingreso"], "monto", "-5")
    assert r.status_code == 422 and r.json()["codigo"] == "MONTO_INVALIDO"


def test_json_mal_formado_y_cuerpos_raros(client, h):
    for contenido, tipo in [(b"{no es json", "application/json"), (b"", "application/json"),
                            (b"[1,2,3]", "application/json"), (b"nulo", "text/plain"),
                            (b"\xff\xfe\x00", "application/json")]:
        r = client.post("/api/v1/tarjetas", content=contenido, headers={**h, "content-type": tipo})
        assert 400 <= r.status_code < 500, (contenido, r.status_code)
        _forma_de_error(r)


@pytest.mark.parametrize("path", ["/api/v1/tarjetas/abc", "/api/v1/tarjetas/-1", "/api/v1/tarjetas/0",
                                  "/api/v1/alertas/99999999999999999999999", "/api/v1/tarjetas/1.5",
                                  "/api/v1/movimientos/gasto-99999999999999999999999",
                                  "/api/v1/movimientos/ingreso-abc", "/api/v1/movimientos/xxx",
                                  "/api/v1/alertas/abc", "/api/v1/msi/1%27%20OR%201=1"])
def test_ids_raros_en_la_url(client, h, path):
    r = client.get(path, headers=h)
    assert 400 <= r.status_code < 500, f"{path}: {r.status_code} {r.text[:200]}"
    _forma_de_error(r)


@pytest.mark.xfail(strict=True, raises=OverflowError,
                   reason="H-05: los ids de la URL no tienen tope; con un número gigante SQLite da 500. "
                          "Ver docs/REVISION_T54.md")
@pytest.mark.parametrize("modulo", ["tarjetas", "deudas", "msi"])
def test_h05_id_gigante_en_la_url(client, h, modulo):
    r = client.get(f"/api/v1/{modulo}/99999999999999999999999", headers=h)
    assert r.status_code == 404


@pytest.mark.parametrize("query", ["mes=2026-13", "mes=abc", "mes=", "mes=9999-99", "mes=2026-03&x=1"])
def test_parametros_de_consulta_raros(client, h, query):
    r = client.get(f"/api/v1/movimientos?{query}", headers=h)
    assert r.status_code < 500, r.text


@pytest.mark.parametrize("query", ["meses=0", "meses=-1", "meses=9999", "meses=abc", "ahorro_inicial=abc",
                                   "ahorro_inicial=-5", "ahorro_inicial=1e400", "ahorro_inicial=NaN"])
def test_parametros_raros_de_la_proyeccion(client, h, query):
    r = client.get(f"/api/v1/proyeccion?{query}", headers=h)
    assert r.status_code < 500, f"{query}: {r.text[:200]}"


# ======================================================================= 4. errores sin detalles internos
@pytest.fixture
def cliente_sin_relanzar():
    """TestClient que devuelve el 500 en lugar de relanzar la excepción, como lo vería un cliente real."""
    return TestClient(app, raise_server_exceptions=False)


def test_un_error_interno_responde_generico(cliente_sin_relanzar, h, monkeypatch):
    from app.services import tarjetas
    secreto = "SELECT * FROM tarjeta WHERE saldo=99999 -- pymysql.err.OperationalError 1045 'root'@'db'"

    def revienta(*a, **k):
        raise RuntimeError(secreto)

    monkeypatch.setattr(tarjetas, "listar", revienta)
    r = cliente_sin_relanzar.get("/api/v1/tarjetas", headers=h)
    assert r.status_code == 500 and r.json() == {"codigo": "ERROR_INTERNO",
                                                 "mensaje": "Ocurrió un error inesperado.", "campos": []}
    assert "SELECT" not in r.text and "root" not in r.text


def test_un_error_de_base_de_datos_tampoco_se_filtra(cliente_sin_relanzar, h, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.services import deudas

    def revienta(*a, **k):
        raise OperationalError("SELECT secreto FROM tabla_interna", {}, Exception("(2003) Can't connect"))

    monkeypatch.setattr(deudas, "listar", revienta)
    r = cliente_sin_relanzar.get("/api/v1/deudas", headers=h)
    assert r.status_code == 500
    assert "tabla_interna" not in r.text and "2003" not in r.text
    _forma_de_error(r)


@pytest.mark.parametrize("metodo,path", [("GET", "/api/v1/no-existe"), ("GET", "/no-existe"),
                                          ("DELETE", "/api/v1/score"), ("POST", "/api/v1/tarjetas/1")])
def test_404_y_405_tienen_el_formato_del_contrato(client, h, metodo, path):
    r = client.request(metodo, path, headers=h)
    assert r.status_code in (404, 405)
    _forma_de_error(r)


def test_un_token_de_recuperacion_no_sirve_como_sesion(client, usuario1):
    from app.core.seguridad import crear_token_recuperacion
    from app.models import Usuario
    from tests.conftest import TestSession
    with TestSession() as db:
        token = crear_token_recuperacion(db.get(Usuario, usuario1[0]))
    r = client.get("/api/v1/tarjetas", headers={"Authorization": f"Bearer {token}"})
    assert (r.status_code, r.json()["codigo"]) == (401, "TOKEN_INVALIDO")


def test_un_token_firmado_con_otra_llave_o_sin_firma_no_sirve(client, usuario1):
    import jwt
    for token in (jwt.encode({"sub": str(usuario1[0])}, "otra-llave", algorithm="HS256"),
                  jwt.encode({"sub": str(usuario1[0])}, "", algorithm="none")):
        r = client.get("/api/v1/tarjetas", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, r.text
