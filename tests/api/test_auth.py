"""/api/auth (T51): me, registro, login, logout y recuperación de contraseña."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.seguridad import crear_token_recuperacion
from app.models import Usuario
from tests.conftest import TestSession

REGISTRO = {"nombre": "Ana Pérez", "correo": "ana@ejemplo.com", "contrasena": "Clave1234",
            "acepta_terminos": True}
BASE = "/api/auth"


def _registrar(client, **cambios):
    return client.post(f"{BASE}/registro", json={**REGISTRO, **cambios})


def _usuario_db(correo: str) -> Usuario | None:
    with TestSession() as db:
        return db.scalar(select(Usuario).where(Usuario.correo == correo))


def _total_usuarios() -> int:
    with TestSession() as db:
        return db.scalar(select(func.count()).select_from(Usuario))


# ------------------------------------------------------------------------------------- /me
def test_me_devuelve_solo_los_datos_publicos(client, h):
    r = client.get(f"{BASE}/me", headers=h)
    assert r.status_code == 200
    assert set(r.json()) == {"id", "nombre", "correo", "moneda"}
    assert r.json()["correo"] == "uno@ejemplo.com"


def test_me_sin_token(client):
    r = client.get(f"{BASE}/me")
    assert r.status_code == 401 and r.json()["codigo"] == "NO_AUTENTICADO"


def test_me_token_invalido(client):
    r = client.get(f"{BASE}/me", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401 and r.json()["codigo"] == "TOKEN_INVALIDO"


# --------------------------------------------------------------------------------- registro
def test_registro_correcto(client):
    r = _registrar(client, correo="  Ana@Ejemplo.COM ")
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"access_token", "token_type", "expira_en", "usuario"}
    assert cuerpo["token_type"] == "bearer"
    assert cuerpo["expira_en"] == settings.jwt_horas * 3600
    assert cuerpo["usuario"]["correo"] == "ana@ejemplo.com"
    assert cuerpo["usuario"]["moneda"] == "MXN"
    guardado = _usuario_db("ana@ejemplo.com")
    assert guardado.contrasena_hash != REGISTRO["contrasena"]
    assert guardado.contrasena_hash.startswith("$argon2")


def test_token_del_registro_sirve(client):
    token = _registrar(client).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get(f"{BASE}/me", headers=h).json()["nombre"] == "Ana Pérez"
    assert client.get("/api/v1/tarjetas", headers=h).status_code == 200


@pytest.mark.parametrize("correo", ["ana@ejemplo.com", "ANA@EJEMPLO.COM", " ana@ejemplo.com "])
def test_registro_correo_repetido(client, correo):
    assert _registrar(client).status_code == 201
    r = _registrar(client, correo=correo)
    assert r.status_code == 409 and r.json()["codigo"] == "CORREO_YA_REGISTRADO"
    assert _total_usuarios() == 1


def test_registro_sin_aceptar_terminos(client):
    r = _registrar(client, acepta_terminos=False)
    assert r.status_code == 422
    assert r.json()["codigo"] == "TERMINOS_NO_ACEPTADOS"
    assert r.json()["campos"][0]["campo"] == "acepta_terminos"
    assert _total_usuarios() == 0


@pytest.mark.parametrize("cambio", [
    {"contrasena": "corta1"},                 # menos de 8
    {"contrasena": "sinnumeroaqui"},          # sin número
    {"contrasena": "12345678"},               # sin letra
    {"contrasena": "a1" * 33},                # más de 64
    {"nombre": "A"},
    {"nombre": "   "},
    {"correo": "no-es-correo"},
    {"correo": "a@b"},
    {"extra": "x"},                           # extra="forbid"
])
def test_registro_datos_invalidos(client, cambio):
    r = _registrar(client, **cambio)
    assert r.status_code == 422 and r.json()["codigo"] == "DATOS_INVALIDOS"
    assert _total_usuarios() == 0


def test_registro_no_recorta_la_contrasena(client):
    assert _registrar(client, contrasena=" Clave1234 ").status_code == 201
    ok = client.post(f"{BASE}/login", json={"correo": REGISTRO["correo"], "contrasena": " Clave1234 "})
    mal = client.post(f"{BASE}/login", json={"correo": REGISTRO["correo"], "contrasena": "Clave1234"})
    assert ok.status_code == 200 and mal.status_code == 401


# -------------------------------------------------------------------------------------- login
def test_login_correcto(client):
    _registrar(client)
    r = client.post(f"{BASE}/login", json={"correo": "ANA@ejemplo.com", "contrasena": "Clave1234"})
    assert r.status_code == 200, r.text
    assert r.json()["usuario"]["correo"] == "ana@ejemplo.com"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"{BASE}/me", headers=h).status_code == 200


def test_login_fallido_es_igual_exista_o_no_el_correo(client):
    _registrar(client)
    mala = client.post(f"{BASE}/login", json={"correo": "ana@ejemplo.com", "contrasena": "Otra12345"})
    inexistente = client.post(f"{BASE}/login", json={"correo": "nadie@ejemplo.com", "contrasena": "Otra12345"})
    assert mala.status_code == inexistente.status_code == 401
    assert mala.json() == inexistente.json()
    assert mala.json()["codigo"] == "CREDENCIALES_INVALIDAS"


def test_login_usuario_con_hash_que_no_es_argon2(client, usuario1):
    r = client.post(f"{BASE}/login", json={"correo": "uno@ejemplo.com", "contrasena": "x"})
    assert r.status_code == 401


# ------------------------------------------------------------------------------------- logout
def test_logout(client, h):
    assert client.post(f"{BASE}/logout", headers=h).status_code == 204
    assert client.post(f"{BASE}/logout").status_code == 204   # también con la sesión vencida


def test_usuario_registrado_puede_borrar_su_cuenta(client):
    token = _registrar(client).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.request("DELETE", "/api/v1/cuenta", json={"contrasena": "Clave1234"}, headers=h)
    assert r.status_code == 204
    assert _total_usuarios() == 0


# ----------------------------------------------------------------------------- recuperación
@pytest.fixture
def enlace_prueba(monkeypatch):
    monkeypatch.setattr(settings, "recuperacion_enlace_prueba", True)


def _token_de(enlace: str) -> str:
    return enlace.split("token=")[1]


def test_recuperar_misma_respuesta_exista_o_no_el_correo(client, enlace_prueba):
    _registrar(client)
    existe = client.post(f"{BASE}/recuperar-contrasena", json={"correo": "ana@ejemplo.com"})
    no_existe = client.post(f"{BASE}/recuperar-contrasena", json={"correo": "nadie@ejemplo.com"})
    assert existe.status_code == no_existe.status_code == 200
    assert existe.json()["mensaje"] == no_existe.json()["mensaje"]
    assert "enlace_prueba" in existe.json()
    assert "enlace_prueba" not in no_existe.json()


def test_recuperar_sin_enlace_de_prueba_no_lo_devuelve(client):
    _registrar(client)
    r = client.post(f"{BASE}/recuperar-contrasena", json={"correo": "ana@ejemplo.com"})
    assert r.status_code == 200 and "enlace_prueba" not in r.json()


def test_restablecer_cambia_la_contrasena(client, enlace_prueba):
    _registrar(client)
    enlace = client.post(f"{BASE}/recuperar-contrasena",
                         json={"correo": "ana@ejemplo.com"}).json()["enlace_prueba"]
    assert enlace.startswith(f"{settings.frontend_url}/restablecer-contrasena?token=")
    token = _token_de(enlace)
    r = client.post(f"{BASE}/restablecer-contrasena", json={"token": token, "contrasena": "Nueva12345"})
    assert r.status_code == 204
    viejo = client.post(f"{BASE}/login", json={"correo": "ana@ejemplo.com", "contrasena": "Clave1234"})
    nuevo = client.post(f"{BASE}/login", json={"correo": "ana@ejemplo.com", "contrasena": "Nueva12345"})
    assert viejo.status_code == 401 and nuevo.status_code == 200


def test_el_enlace_solo_sirve_una_vez(client, enlace_prueba):
    _registrar(client)
    token = _token_de(client.post(f"{BASE}/recuperar-contrasena",
                                  json={"correo": "ana@ejemplo.com"}).json()["enlace_prueba"])
    assert client.post(f"{BASE}/restablecer-contrasena",
                       json={"token": token, "contrasena": "Nueva12345"}).status_code == 204
    r = client.post(f"{BASE}/restablecer-contrasena", json={"token": token, "contrasena": "Otra123456"})
    assert r.status_code == 400 and r.json()["codigo"] == "ENLACE_INVALIDO"


def test_restablecer_token_vencido(client):
    uid = _registrar(client).json()["usuario"]["id"]
    with TestSession() as db:
        usuario = db.get(Usuario, uid)
        vigente = crear_token_recuperacion(usuario)
    datos = jwt.decode(vigente, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    datos["exp"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    vencido = jwt.encode(datos, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    r = client.post(f"{BASE}/restablecer-contrasena", json={"token": vencido, "contrasena": "Nueva12345"})
    assert r.status_code == 400 and r.json()["codigo"] == "ENLACE_INVALIDO"


def test_token_de_sesion_no_sirve_para_restablecer(client):
    sesion = _registrar(client).json()
    r = client.post(f"{BASE}/restablecer-contrasena",
                    json={"token": sesion["access_token"], "contrasena": "Nueva12345"})
    assert r.status_code == 400


def test_token_de_recuperacion_no_sirve_como_sesion(client):
    uid = _registrar(client).json()["usuario"]["id"]
    with TestSession() as db:
        token = crear_token_recuperacion(db.get(Usuario, uid))
    r = client.get(f"{BASE}/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["codigo"] == "TOKEN_INVALIDO"


def test_restablecer_contrasena_debil(client, enlace_prueba):
    _registrar(client)
    token = _token_de(client.post(f"{BASE}/recuperar-contrasena",
                                  json={"correo": "ana@ejemplo.com"}).json()["enlace_prueba"])
    r = client.post(f"{BASE}/restablecer-contrasena", json={"token": token, "contrasena": "corta"})
    assert r.status_code == 422
    # el enlace sigue sirviendo: la validación falló antes de usarlo
    assert client.post(f"{BASE}/restablecer-contrasena",
                       json={"token": token, "contrasena": "Nueva12345"}).status_code == 204
