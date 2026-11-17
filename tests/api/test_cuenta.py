"""DELETE /api/v1/cuenta (T56): pide la contraseña y borra todo lo del usuario."""
from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.core.database import Base
from app.core.seguridad import crear_token, hash_contrasena
from app.models import (Alerta, AlertaConfiguracion, Categoria, Deuda, EstadoCuenta, Gasto, Ingreso, Movimiento, PlanMsi,
                        ScoreHistorial, Tarjeta, Usuario)
from tests.conftest import DEUDA, TARJETA, TestSession

URL = "/api/v1/cuenta"
CLAVE = "Clave de prueba 123"


@pytest.fixture(scope="module")
def hash_clave():
    return hash_contrasena(CLAVE)   # una sola vez: Argon2 es lento a propósito


def _usuario(correo: str, hash_: str):
    with TestSession() as db:
        u = Usuario(nombre="Prueba", correo=correo, contrasena_hash=hash_, moneda="MXN")
        db.add(u)
        db.commit()
        return u.id, {"Authorization": f"Bearer {crear_token(u.id)}"}


@pytest.fixture
def cuenta(hash_clave):
    """(id, headers) de un usuario con contraseña real."""
    return _usuario("borrar@ejemplo.com", hash_clave)


def _eliminar(client, headers, contrasena=CLAVE):
    return client.request("DELETE", URL, json={"contrasena": contrasena}, headers=headers)


def _llenar(client, uid: int, h: dict, cat_base: int) -> None:
    """Un registro, como mínimo, en cada tabla que guarda datos del usuario."""
    def crear(ruta, cuerpo):
        r = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=h)
        assert r.status_code == 201, r.text
        return r.json()

    tarjeta = crear("tarjetas", TARJETA)
    propia = crear("categorias", {"nombre": "Mascotas"})
    plan = crear("msi", {"tarjeta_id": tarjeta["id"], "categoria_id": propia["id"],
                         "descripcion": "Laptop", "monto_original": 12000,
                         "num_mensualidades": 12, "fecha_compra": "2026-01-10"})
    crear("deudas", DEUDA)
    crear("movimientos", {"tipo": "ingreso", "concepto": "Sueldo", "monto": 20000,
                          "frecuencia": "mensual", "fecha": "2026-03-01"})
    crear("movimientos", {"tipo": "gasto", "concepto": "Croquetas", "monto": 500,
                          "fecha": "2026-03-10", "categoria_id": propia["id"], "clase": "variable"})
    crear("movimientos", {"tipo": "gasto", "concepto": "Renta", "monto": 8000,
                          "frecuencia": "mensual", "fecha": "2026-03-01",
                          "categoria_id": cat_base, "clase": "fijo"})
    # Umbral bajo: la tarjeta (25 % usado) genera una alerta y deja guardada la configuración.
    r = client.put("/api/v1/alertas/configuracion", json={"umbral_utilizacion": 10}, headers=h)
    assert r.status_code == 200, r.text
    # Estado de cuenta, movimiento e historial de score no tienen endpoint de alta.
    with TestSession() as db:
        estado = EstadoCuenta(tarjeta_id=tarjeta["id"], periodo_inicio=date(2026, 2, 11),
                              fecha_corte=date(2026, 3, 10), fecha_limite_pago=date(2026, 3, 30),
                              saldo_al_corte=5000, estatus="revisado")
        db.add(estado)
        db.flush()
        db.add(Movimiento(estado_cuenta_id=estado.id, origen="extraido", fecha=date(2026, 3, 1),
                          descripcion="Mensualidad laptop", monto=1000, tipo="mensualidad_msi",
                          categoria_id=propia["id"], plan_msi_id=plan["id"]))
        db.add(ScoreHistorial(usuario_id=uid, calculado_en=datetime(2026, 3, 15, 12, 0),
                              puntaje=70, version_modelo="prueba", componentes={}))
        db.commit()


def _conteos(uid: int) -> dict[str, int]:
    """Filas de cada tabla que pertenecen al usuario."""
    tarjetas = select(Tarjeta.id).where(Tarjeta.usuario_id == uid)
    estados = select(EstadoCuenta.id).where(EstadoCuenta.tarjeta_id.in_(tarjetas))
    filtros = {
        "usuario": (Usuario, Usuario.id == uid),
        "categoria": (Categoria, Categoria.usuario_id == uid),
        "ingreso": (Ingreso, Ingreso.usuario_id == uid),
        "gasto": (Gasto, Gasto.usuario_id == uid),
        "tarjeta": (Tarjeta, Tarjeta.usuario_id == uid),
        "estado_cuenta": (EstadoCuenta, EstadoCuenta.tarjeta_id.in_(tarjetas)),
        "movimiento": (Movimiento, Movimiento.estado_cuenta_id.in_(estados)),
        "plan_msi": (PlanMsi, PlanMsi.tarjeta_id.in_(tarjetas)),
        "deuda": (Deuda, Deuda.usuario_id == uid),
        "score_historial": (ScoreHistorial, ScoreHistorial.usuario_id == uid),
        "alerta": (Alerta, Alerta.usuario_id == uid),
        "alerta_configuracion": (AlertaConfiguracion, AlertaConfiguracion.usuario_id == uid),
    }
    with TestSession() as db:
        return {nombre: db.scalar(select(func.count()).select_from(modelo).where(filtro))
                for nombre, (modelo, filtro) in filtros.items()}


def _filas_por_tabla() -> dict[str, int]:
    """Filas totales de cada tabla de la base, sin filtrar por usuario."""
    with TestSession() as db:
        return {t.name: db.scalar(select(func.count()).select_from(t))
                for t in Base.metadata.sorted_tables}


def test_requiere_token(client):
    r = client.request("DELETE", URL, json={"contrasena": CLAVE})
    assert r.status_code == 401 and r.json()["codigo"] == "NO_AUTENTICADO"


@pytest.mark.parametrize("cuerpo", [{}, {"contrasena": ""}, {"contrasena": CLAVE, "otro": 1}])
def test_cuerpo_invalido(client, cuenta, cuerpo):
    uid, h = cuenta
    r = client.request("DELETE", URL, json=cuerpo, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "DATOS_INVALIDOS"
    assert _conteos(uid)["usuario"] == 1


@pytest.mark.parametrize("mala", ["otra-clave", CLAVE.lower(), CLAVE + " ", " " + CLAVE])
def test_contrasena_incorrecta_no_borra_nada(client, cuenta, cat, mala):
    uid, h = cuenta
    _llenar(client, uid, h, cat)
    antes = _conteos(uid)

    r = _eliminar(client, h, mala)

    assert r.status_code == 403 and r.json()["codigo"] == "CONTRASENA_INCORRECTA"
    assert r.json()["campos"][0]["campo"] == "contrasena"
    assert _conteos(uid) == antes
    assert client.get("/api/v1/tarjetas", headers=h).status_code == 200   # la sesión sigue viva


def test_usuario_sin_hash_valido_no_se_puede_borrar(client, h, usuario1):
    """Los usuarios creados a mano tienen contrasena_hash="x": ninguna contraseña coincide."""
    assert _eliminar(client, h, "x").status_code == 403
    assert _conteos(usuario1[0])["usuario"] == 1


def test_elimina_todo_lo_del_usuario(client, cuenta, cat):
    uid, h = cuenta
    _llenar(client, uid, h, cat)
    antes = _conteos(uid)
    assert all(n > 0 for n in antes.values()), antes   # había datos en todas las tablas

    r = _eliminar(client, h)

    assert r.status_code == 204 and r.content == b""
    assert _conteos(uid) == dict.fromkeys(antes, 0)
    # No quedó nada en la base, salvo la categoría base (no es del usuario).
    assert _filas_por_tabla() == {**dict.fromkeys(antes, 0), "categoria": 1}


def test_el_token_deja_de_servir(client, cuenta):
    _, h = cuenta
    assert _eliminar(client, h).status_code == 204
    r = client.get("/api/v1/tarjetas", headers=h)
    assert r.status_code == 401 and r.json()["codigo"] == "TOKEN_INVALIDO"
    assert _eliminar(client, h).status_code == 401   # repetirlo no hace nada


def test_no_toca_los_datos_de_otro_usuario(client, cuenta, cat, hash_clave):
    uid, h = cuenta
    otro, h_otro = _usuario("otro@ejemplo.com", hash_clave)
    _llenar(client, uid, h, cat)
    _llenar(client, otro, h_otro, cat)
    antes_otro = _conteos(otro)

    assert _eliminar(client, h).status_code == 204

    assert _conteos(otro) == antes_otro
    assert len(client.get("/api/v1/tarjetas", headers=h_otro).json()) == 1


def test_se_puede_volver_a_registrar_el_correo(client, cuenta, hash_clave):
    _, h = cuenta
    assert _eliminar(client, h).status_code == 204
    _usuario("borrar@ejemplo.com", hash_clave)   # el correo (único) quedó libre


def test_toda_llave_foranea_define_que_pasa_al_borrar():
    """Guardiana para tablas futuras (alertas, simulaciones, suscripciones push): si una tabla
    con datos del usuario no borra en cascada, DELETE /cuenta fallaría o dejaría huérfanos."""
    for tabla in Base.metadata.sorted_tables:
        for fk in tabla.foreign_keys:
            donde = f"{tabla.name}.{fk.parent.name}"
            assert fk.ondelete in ("CASCADE", "SET NULL", "RESTRICT"), f"{donde} no define ondelete"
            if fk.column.table.name == "usuario":
                assert fk.ondelete == "CASCADE", f"{donde} debe borrar en cascada con el usuario"
