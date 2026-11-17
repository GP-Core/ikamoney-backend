"""Alertas (T47): no se repiten, se resuelven, se reactivan sin avisar de nuevo y se aíslan por usuario."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import Alerta, Usuario
from app.services import alertas as servicio
from app.services import fechas
from app.services.alertas_reglas import Hallazgo
from tests.conftest import DEUDA, TARJETA, TestSession

URL = "/api/v1/alertas"
ALTA = {**TARJETA, "saldo_actual": 15000}     # 75 % de 20,000: sobre el umbral por defecto (70 %)


def _filas() -> list[Alerta]:
    with TestSession() as db:
        return list(db.scalars(select(Alerta).order_by(Alerta.id)))


def _lista(client, h, **params):
    r = client.get(URL, headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _tarjeta(client, h, cuerpo=ALTA):
    r = client.post("/api/v1/tarjetas", json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _saldo(client, h, tid, saldo):
    r = client.put(f"/api/v1/tarjetas/{tid}", json={"saldo_actual": saldo}, headers=h)
    assert r.status_code == 200, r.text


@pytest.fixture
def reloj(monkeypatch):
    """Hora controlada para probar el enfriamiento: devuelve una función que la mueve."""
    estado = {"t": datetime(2026, 3, 15, 12, 0, 0)}
    monkeypatch.setattr(servicio, "ahora", lambda: estado["t"])

    def mover(**delta):
        estado["t"] += timedelta(**delta)
    return mover


# ------------------------------------------------------------ crear y no repetir
def test_requiere_token(client):
    assert client.get(URL).status_code == 401
    assert client.patch(f"{URL}/1", json={"leida": True}).status_code == 401
    assert client.get(f"{URL}/configuracion").status_code == 401
    assert client.put(f"{URL}/configuracion", json={"umbral_utilizacion": 50}).status_code == 401


def test_sin_datos_no_hay_alertas(client, h):
    assert _lista(client, h) == {"total": 0, "sin_leer": 0, "alertas": []}


def test_una_tarjeta_sobre_el_umbral_genera_una_alerta(client, h):
    _tarjeta(client, h)
    cuerpo = _lista(client, h)
    assert cuerpo["total"] == 1 and cuerpo["sin_leer"] == 1
    a = cuerpo["alertas"][0]
    assert (a["regla"], a["severidad"], a["estado"], a["leida"]) == ("AL-02", "atencion", "activa", False)
    assert "BBVA Azul" in a["titulo"] and a["resuelta_en"] is None
    assert set(a) == {"id", "regla", "severidad", "titulo", "mensaje", "accion", "referencia",
                      "estado", "leida", "creada_en", "resuelta_en"}


def test_varias_escrituras_no_duplican_la_alerta(client, h):
    tid = _tarjeta(client, h)
    for saldo in (15100, 15200, 15300, 15400):
        _saldo(client, h, tid, saldo)
    client.post("/api/v1/deudas", json=DEUDA, headers=h)
    client.post("/api/v1/movimientos", headers=h, json={
        "tipo": "gasto", "concepto": "Comida", "monto": 100, "fecha": "2026-03-10", "clase": "variable"})
    assert len(_filas()) == 1 and _lista(client, h)["total"] == 1


def test_una_alerta_leida_sigue_activa_y_no_se_vuelve_a_generar(client, h):
    tid = _tarjeta(client, h)
    aid = _lista(client, h)["alertas"][0]["id"]
    r = client.patch(f"{URL}/{aid}", json={"leida": True}, headers=h)
    assert r.status_code == 200 and r.json()["leida"] is True
    _saldo(client, h, tid, 16000)
    cuerpo = _lista(client, h)
    assert (cuerpo["total"], cuerpo["sin_leer"]) == (1, 0) and len(_filas()) == 1
    r = client.patch(f"{URL}/{aid}", json={"leida": False}, headers=h)
    assert r.json()["leida"] is False and _lista(client, h)["sin_leer"] == 1


def test_el_unique_de_la_base_impide_dos_activas_iguales(usuario1):
    hallazgo = Hallazgo("AL-02", "tarjeta:1", "atencion", "t", "m", "a")
    with TestSession() as db:
        u = db.get(Usuario, usuario1[0])
        assert servicio._crear(db, u, hallazgo, datetime(2026, 3, 15)) is True
        assert servicio._crear(db, u, hallazgo, datetime(2026, 3, 15)) is False   # la otra petición pierde
        db.commit()
        assert db.scalar(select(func.count()).select_from(Alerta)) == 1


# ------------------------------------------------------------ resolver y reactivar
def test_al_bajar_el_saldo_la_alerta_se_resuelve(client, h):
    tid = _tarjeta(client, h)
    _saldo(client, h, tid, 1000)
    assert _lista(client, h) == {"total": 0, "sin_leer": 0, "alertas": []}
    [a] = _lista(client, h, estado="todas")["alertas"]
    assert a["estado"] == "resuelta" and a["resuelta_en"] is not None
    assert _lista(client, h, estado="resuelta")["total"] == 1


def test_oscilar_dentro_del_enfriamiento_reactiva_la_misma_fila(client, h, reloj):
    tid = _tarjeta(client, h)
    _saldo(client, h, tid, 1000)
    reloj(hours=23)
    _saldo(client, h, tid, 15000)
    filas = _filas()
    assert len(filas) == 1 and filas[0].estado == "activa" and filas[0].resuelta_en is None
    assert filas[0].clave_activa == f"AL-02|tarjeta:{tid}"


def test_pasado_el_enfriamiento_se_crea_una_alerta_nueva(client, h, reloj):
    tid = _tarjeta(client, h)
    _saldo(client, h, tid, 1000)
    reloj(hours=25)
    _saldo(client, h, tid, 15000)
    filas = _filas()
    assert [f.estado for f in filas] == ["resuelta", "activa"] and filas[0].id != filas[1].id


def test_sobre_el_limite_cambia_de_al02_a_al04(client, h):
    tid = _tarjeta(client, h)
    _saldo(client, h, tid, 21000)
    assert [a["regla"] for a in _lista(client, h)["alertas"]] == ["AL-04"]
    assert [a["regla"] for a in _lista(client, h, estado="resuelta")["alertas"]] == ["AL-02"]


def test_al03_aparece_con_los_dias_y_no_se_repite(client, h, monkeypatch):
    tid = _tarjeta(client, h, {**TARJETA, "saldo_actual": 1000})       # 5 %: sin AL-02; paga el 30
    assert _lista(client, h)["total"] == 0
    monkeypatch.setattr(fechas, "hoy_mx", lambda: date(2026, 3, 28))   # faltan 2 días
    _saldo(client, h, tid, 1100)
    _saldo(client, h, tid, 1200)
    [a] = _lista(client, h)["alertas"]
    assert a["regla"] == "AL-03" and a["referencia"] == f"tarjeta:{tid}:2026-03-30"
    assert "30 de marzo" in a["mensaje"]
    monkeypatch.setattr(fechas, "hoy_mx", lambda: date(2026, 3, 31))   # ya pasó
    _saldo(client, h, tid, 1300)
    assert _lista(client, h)["total"] == 0


def test_al01_con_compromisos_mayores_que_ingresos(client, h):
    client.post("/api/v1/movimientos", headers=h, json={
        "tipo": "ingreso", "concepto": "Sueldo", "monto": 1000, "frecuencia": "mensual",
        "fecha": "2026-03-01"})
    client.post("/api/v1/deudas", json=DEUDA, headers=h)               # paga 4,500 al mes
    [a] = _lista(client, h)["alertas"]
    assert (a["regla"], a["severidad"], a["referencia"]) == ("AL-01", "critica", "proyeccion")
    assert "marzo de 2026" in a["mensaje"]


def test_eliminar_la_tarjeta_resuelve_su_alerta(client, h):
    tid = _tarjeta(client, h)
    client.delete(f"/api/v1/tarjetas/{tid}", headers=h)
    assert _lista(client, h)["total"] == 0


# ------------------------------------------------------------ IC-07
def test_la_respuesta_no_trae_saldos(client, h):
    _tarjeta(client, h, {**ALTA, "saldo_actual": 15234.56, "limite_credito": 20123})
    texto = client.get(URL, headers=h).text
    for numero in ("15234", "15,234", "20123", "20,123"):
        assert numero not in texto


# ------------------------------------------------------------ configuración
def test_configuracion_por_defecto(client, h):
    r = client.get(f"{URL}/configuracion", headers=h)
    assert r.json() == {"umbral_utilizacion": 70, "dias_anticipacion": 3,
                        "canales": {"correo": True, "push": False}}


def test_cambiar_el_umbral_reevalua_las_alertas(client, h):
    _tarjeta(client, h)                                                # 75 %
    r = client.put(f"{URL}/configuracion", json={"umbral_utilizacion": 80}, headers=h)
    assert r.json()["umbral_utilizacion"] == 80
    assert _lista(client, h)["total"] == 0
    client.put(f"{URL}/configuracion", json={"umbral_utilizacion": 50}, headers=h)
    assert [a["regla"] for a in _lista(client, h)["alertas"]] == ["AL-02"]
    assert client.get(f"{URL}/configuracion", headers=h).json()["umbral_utilizacion"] == 50


def test_put_parcial_solo_cambia_lo_enviado(client, h):
    client.put(f"{URL}/configuracion", json={"dias_anticipacion": 7}, headers=h)
    r = client.put(f"{URL}/configuracion", json={"canales": {"push": True}}, headers=h)
    assert r.json() == {"umbral_utilizacion": 70, "dias_anticipacion": 7,
                        "canales": {"correo": True, "push": True}}


@pytest.mark.parametrize("cuerpo", [
    {}, {"umbral_utilizacion": 9}, {"umbral_utilizacion": 101}, {"umbral_utilizacion": 50.5},
    {"umbral_utilizacion": None}, {"dias_anticipacion": 0}, {"dias_anticipacion": 16},
    {"canales": None}, {"canales": {"correo": None}}, {"canales": {"sms": True}},
    {"canales": {}}, {"otro": 1}, {"umbral_utilizacion": "alto"}])
def test_configuracion_invalida(client, h, cuerpo):
    r = client.put(f"{URL}/configuracion", json=cuerpo, headers=h)
    assert r.status_code == 422 and r.json()["codigo"] == "DATOS_INVALIDOS"
    assert client.get(f"{URL}/configuracion", headers=h).json()["umbral_utilizacion"] == 70


def test_los_limites_del_rango_se_aceptan(client, h):
    for cuerpo in ({"umbral_utilizacion": 10}, {"umbral_utilizacion": 100},
                   {"dias_anticipacion": 1}, {"dias_anticipacion": 15}):
        assert client.put(f"{URL}/configuracion", json=cuerpo, headers=h).status_code == 200


# ------------------------------------------------------------ aislamiento y validación
def test_otro_usuario_no_ve_ni_toca_mis_alertas(client, h, h2):
    _tarjeta(client, h)
    aid = _lista(client, h)["alertas"][0]["id"]
    assert _lista(client, h2) == {"total": 0, "sin_leer": 0, "alertas": []}
    r = client.patch(f"{URL}/{aid}", json={"leida": True}, headers=h2)
    assert (r.status_code, r.json()["codigo"]) == (404, "ALERTA_NO_ENCONTRADA")
    assert client.patch(f"{URL}/99999", json={"leida": True}, headers=h).status_code == 404
    assert _lista(client, h)["sin_leer"] == 1


def test_la_configuracion_es_por_usuario(client, h, h2):
    client.put(f"{URL}/configuracion", json={"umbral_utilizacion": 20}, headers=h)
    assert client.get(f"{URL}/configuracion", headers=h2).json()["umbral_utilizacion"] == 70


def test_la_alerta_de_otro_usuario_no_afecta(client, h, h2):
    _tarjeta(client, h2)
    assert _lista(client, h)["total"] == 0 and _lista(client, h2)["total"] == 1


@pytest.mark.parametrize("cuerpo", [{}, {"leida": "tal vez"}, {"leida": True, "id": 3}])
def test_patch_invalido(client, h, cuerpo):
    _tarjeta(client, h)
    aid = _lista(client, h)["alertas"][0]["id"]
    assert client.patch(f"{URL}/{aid}", json=cuerpo, headers=h).status_code == 422


@pytest.mark.parametrize("params", [{"estado": "otra"}, {"limite": 0}, {"limite": 101}])
def test_filtros_invalidos(client, h, params):
    assert client.get(URL, headers=h, params=params).status_code == 422


def test_mas_recientes_primero(client, h, reloj):
    _tarjeta(client, h)
    reloj(hours=1)
    _tarjeta(client, h, {**ALTA, "nombre": "Nu"})
    nombres = [a["titulo"] for a in _lista(client, h)["alertas"]]
    assert "Nu" in nombres[0] and "BBVA Azul" in nombres[1]


# ------------------------------------------------------------ revisión diaria (cron)
RUTA_CRON = "/api/internos/revision-diaria"


@pytest.fixture
def llave(monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "llave-de-prueba")
    return {"X-Llave-Interna": "llave-de-prueba"}


def test_cron_cerrado_si_no_hay_llave_configurada(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "")
    for cab in ({}, {"X-Llave-Interna": ""}, {"X-Llave-Interna": "cualquiera"}):
        r = client.post(RUTA_CRON, headers=cab)
        assert (r.status_code, r.json()["codigo"]) == (503, "CRON_NO_CONFIGURADO")


@pytest.mark.parametrize("cab", [{}, {"X-Llave-Interna": ""}, {"X-Llave-Interna": "otra"},
                                 {"Authorization": "Bearer llave-de-prueba"}])
def test_cron_rechaza_llaves_incorrectas(client, llave, cab):
    r = client.post(RUTA_CRON, headers=cab)
    assert (r.status_code, r.json()["codigo"]) == (401, "LLAVE_INVALIDA")


def test_cron_no_acepta_el_token_de_un_usuario(client, llave, h):
    assert client.post(RUTA_CRON, headers=h).status_code == 401


def test_cron_solo_acepta_post(client, llave):
    assert client.get(RUTA_CRON, headers=llave).status_code == 405


def test_cron_revisa_a_todos_y_genera_alertas_por_el_paso_del_tiempo(client, llave, h, h2, monkeypatch):
    _tarjeta(client, h, {**TARJETA, "saldo_actual": 1000})
    _tarjeta(client, h2, {**TARJETA, "saldo_actual": 1000})
    assert _filas() == []
    monkeypatch.setattr(fechas, "hoy_mx", lambda: date(2026, 3, 28))   # sin que nadie escriba
    r = client.post(RUTA_CRON, headers=llave)
    assert r.status_code == 200
    assert r.json() == {"usuarios_revisados": 2, "alertas_nuevas": 2, "alertas_resueltas": 0,
                        "avisos_enviados": 0, "errores": 0}
    # una segunda corrida el mismo día no repite nada
    assert client.post(RUTA_CRON, headers=llave).json()["alertas_nuevas"] == 0
    assert len(_filas()) == 2


def test_un_usuario_que_falla_no_detiene_a_los_demas(client, llave, h, h2, monkeypatch):
    _tarjeta(client, h, {**TARJETA, "saldo_actual": 1000})
    _tarjeta(client, h2, {**TARJETA, "saldo_actual": 1000})
    monkeypatch.setattr(fechas, "hoy_mx", lambda: date(2026, 3, 28))
    original = servicio.revisar
    primero = {}

    def falla_con_el_primero(db, usuario):
        primero.setdefault("id", usuario.id)
        if usuario.id == primero["id"]:
            raise RuntimeError("falla interna")
        return original(db, usuario)

    monkeypatch.setattr(servicio, "revisar", falla_con_el_primero)
    r = client.post(RUTA_CRON, headers=llave)
    assert r.status_code == 200
    assert (r.json()["usuarios_revisados"], r.json()["errores"], r.json()["alertas_nuevas"]) == (1, 1, 1)
    assert "falla interna" not in r.text


def test_la_respuesta_del_cron_no_trae_datos_personales(client, llave, h):
    _tarjeta(client, h)
    r = client.post(RUTA_CRON, headers=llave)
    assert set(r.json()) == {"usuarios_revisados", "alertas_nuevas", "alertas_resueltas",
                             "avisos_enviados", "errores"}
