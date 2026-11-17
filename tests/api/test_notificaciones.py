"""Correo de alertas (T50): respeta la configuración, no se repite, no lleva saldos y no rompe nada si falla."""
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Alerta
from app.services import alertas as servicio_alertas
from app.services import fechas, notificaciones
from app.services.notificaciones import ErrorEnvio
from app.services.notificaciones.brevo import BrevoCliente
from tests.conftest import TARJETA, TestSession

ALTA = {**TARJETA, "saldo_actual": 15234.56, "limite_credito": 20123}   # cifras fáciles de rastrear
CONFIG = "/api/v1/alertas/configuracion"
CRON = "/api/internos/revision-diaria"


class CorreoFalso:
    def __init__(self, falla=False):
        self.enviados: list[dict] = []
        self.falla = falla

    def enviar(self, destinatario, asunto, texto, html):
        if self.falla:
            raise ErrorEnvio("el proveedor respondió 503")
        self.enviados.append({"a": destinatario, "asunto": asunto, "texto": texto, "html": html})


@pytest.fixture
def correo(monkeypatch):
    falso = CorreoFalso()
    monkeypatch.setattr(notificaciones, "cliente_correo", lambda: falso)
    return falso


@pytest.fixture
def llave(monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "llave-de-prueba")
    return {"X-Llave-Interna": "llave-de-prueba"}


def _filas():
    with TestSession() as db:
        return list(db.scalars(select(Alerta).order_by(Alerta.id)))


def _tarjeta(client, h, cuerpo=ALTA):
    r = client.post("/api/v1/tarjetas", json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _saldo(client, h, tid, saldo):
    assert client.put(f"/api/v1/tarjetas/{tid}", json={"saldo_actual": saldo}, headers=h).status_code == 200


# ------------------------------------------------------------ cuándo se envía
def test_una_alerta_nueva_manda_un_correo_al_usuario(client, h, correo):
    _tarjeta(client, h)
    [c] = correo.enviados
    assert c["a"] == "uno@ejemplo.com"
    assert c["asunto"] == "IKAMONEY: tienes un aviso nuevo"
    assert "BBVA Azul" in c["texto"] and "/alertas" in c["texto"] and "/alertas" in c["html"]
    assert _filas()[0].notificada_en is not None


def test_no_se_repite_el_correo_en_las_siguientes_escrituras(client, h, correo):
    tid = _tarjeta(client, h)
    for saldo in (15300, 15400, 15500):
        _saldo(client, h, tid, saldo)
    assert len(correo.enviados) == 1


def test_una_alerta_leida_o_resuelta_y_reactivada_no_se_vuelve_a_avisar(client, h, correo, monkeypatch):
    tid = _tarjeta(client, h)
    ahora = datetime(2026, 3, 15, 12, 0)
    monkeypatch.setattr(servicio_alertas, "ahora", lambda: ahora)
    _saldo(client, h, tid, 1000)
    monkeypatch.setattr(servicio_alertas, "ahora", lambda: ahora + timedelta(hours=3))
    _saldo(client, h, tid, 15000)             # misma fila reactivada dentro del enfriamiento
    assert len(correo.enviados) == 1


def test_varias_alertas_nuevas_van_en_un_solo_correo(client, h, correo):
    client.post("/api/v1/movimientos", headers=h, json={
        "tipo": "ingreso", "concepto": "Sueldo", "monto": 1000, "frecuencia": "mensual",
        "fecha": "2026-03-01"})
    client.post("/api/v1/tarjetas", json=ALTA, headers=h)
    client.post("/api/v1/deudas", headers=h, json={
        "nombre": "Préstamo", "tipo": "otro", "monto_original": 9000, "saldo_actual": 9000,
        "pago_mensual": 4500})
    assert len(_filas()) >= 2
    assert all(f.notificada_en is not None for f in _filas())
    asuntos = [c["asunto"] for c in correo.enviados]
    assert asuntos[-1] in {"IKAMONEY: tienes un aviso nuevo", "IKAMONEY: tienes avisos nuevos"}


# ------------------------------------------------------------ configuración (US 10.2)
def test_con_el_correo_apagado_no_se_envia_nada(client, h, correo):
    client.put(CONFIG, json={"canales": {"correo": False}}, headers=h)
    _tarjeta(client, h)
    assert correo.enviados == []
    assert _filas()[0].notificada_en is None and len(_filas()) == 1   # la alerta sí existe en la app


def test_al_prender_el_correo_se_avisa_lo_pendiente_en_la_revision_diaria(client, h, correo, llave):
    client.put(CONFIG, json={"canales": {"correo": False}}, headers=h)
    _tarjeta(client, h)
    client.put(CONFIG, json={"canales": {"correo": True}}, headers=h)
    assert correo.enviados == []                    # prenderlo no dispara nada por sí solo
    r = client.post(CRON, headers=llave)
    assert r.json()["avisos_enviados"] == 1 and len(correo.enviados) == 1


def test_el_correo_apagado_de_uno_no_afecta_a_otro(client, h, h2, correo):
    client.put(CONFIG, json={"canales": {"correo": False}}, headers=h)
    _tarjeta(client, h)
    _tarjeta(client, h2)
    assert [c["a"] for c in correo.enviados] == ["dos@ejemplo.com"]


def test_sin_llave_del_proveedor_no_se_envia_y_nada_falla(client, h, monkeypatch):
    monkeypatch.setattr(settings, "correo_api_key", "")
    notificaciones.cliente_correo.cache_clear()
    _tarjeta(client, h)
    assert _filas()[0].notificada_en is None


# ------------------------------------------------------------ fallas
def test_si_el_proveedor_falla_la_escritura_del_usuario_sigue_bien(client, h, monkeypatch):
    monkeypatch.setattr(notificaciones, "cliente_correo", lambda: CorreoFalso(falla=True))
    r = client.post("/api/v1/tarjetas", json=ALTA, headers=h)
    assert r.status_code == 201
    assert len(_filas()) == 1 and _filas()[0].notificada_en is None


def test_una_excepcion_inesperada_al_enviar_tampoco_rompe_la_escritura(client, h, monkeypatch):
    class Roto:
        def enviar(self, *a):
            raise RuntimeError("falla interna")
    monkeypatch.setattr(notificaciones, "cliente_correo", lambda: Roto())
    assert client.post("/api/v1/tarjetas", json=ALTA, headers=h).status_code == 201


def test_lo_que_fallo_se_reintenta_en_la_revision_diaria(client, h, monkeypatch, llave):
    monkeypatch.setattr(notificaciones, "cliente_correo", lambda: CorreoFalso(falla=True))
    _tarjeta(client, h)
    bueno = CorreoFalso()
    monkeypatch.setattr(notificaciones, "cliente_correo", lambda: bueno)
    r = client.post(CRON, headers=llave)
    assert r.json()["avisos_enviados"] == 1 and len(bueno.enviados) == 1
    assert client.post(CRON, headers=llave).json()["avisos_enviados"] == 0   # y ya no se repite


def test_una_alerta_de_hace_mas_de_48_horas_ya_no_se_avisa(client, h, monkeypatch, llave):
    monkeypatch.setattr(notificaciones, "cliente_correo", lambda: CorreoFalso(falla=True))
    _tarjeta(client, h)
    bueno = CorreoFalso()
    monkeypatch.setattr(notificaciones, "cliente_correo", lambda: bueno)
    monkeypatch.setattr(fechas, "hoy_mx", lambda: date(2026, 3, 18))     # tres días después
    assert client.post(CRON, headers=llave).json()["avisos_enviados"] == 0
    assert bueno.enviados == []


# ------------------------------------------------------------ IC-07: sin saldos
def test_ni_el_asunto_ni_el_cuerpo_llevan_saldos(client, h, correo):
    client.put(CONFIG, json={"umbral_utilizacion": 10}, headers=h)
    _tarjeta(client, h)
    client.post("/api/v1/deudas", headers=h, json={
        "nombre": "Auto", "tipo": "credito_auto", "monto_original": 987654, "saldo_actual": 876543,
        "pago_mensual": 54321})
    assert correo.enviados
    for c in correo.enviados:
        contenido = " ".join((c["asunto"], c["texto"], c["html"]))
        for cifra in ("15234", "15,234", "20123", "20,123", "987654", "876543", "54321", "54,321", "$"):
            assert cifra not in contenido, cifra


def test_el_nombre_del_usuario_se_escapa_en_el_html():
    class A:
        titulo, mensaje, accion = "t", "m", "a"
    _, texto, html = notificaciones.plantillas.armar("<script>x</script>", [A()], "https://x/alertas")
    assert "<script>" not in html and "&lt;script&gt;" in html


# ------------------------------------------------------------ cliente HTTP
def _brevo(manejador):
    http = httpx.Client(transport=httpx.MockTransport(manejador))
    return BrevoCliente("LLAVE-SECRETA", "avisos@ikamoney.dev", "IKAMONEY",
                        "https://api.brevo.com/v3/smtp/email", 5, cliente=http)


def test_brevo_manda_la_peticion_con_el_formato_de_la_api():
    vistas = []

    def manejador(req: httpx.Request):
        vistas.append(req)
        return httpx.Response(201, json={"messageId": "x"})

    _brevo(manejador).enviar("ana@ejemplo.com", "Asunto", "texto", "<p>html</p>")
    [req] = vistas
    assert str(req.url) == "https://api.brevo.com/v3/smtp/email" and req.method == "POST"
    assert req.headers["api-key"] == "LLAVE-SECRETA"
    import json
    cuerpo = json.loads(req.content)
    assert cuerpo == {"sender": {"name": "IKAMONEY", "email": "avisos@ikamoney.dev"},
                      "to": [{"email": "ana@ejemplo.com"}], "subject": "Asunto",
                      "textContent": "texto", "htmlContent": "<p>html</p>"}


def test_brevo_traduce_los_errores_sin_filtrar_llave_ni_cuerpo():
    cliente = _brevo(lambda req: httpx.Response(401, json={"message": "ana@ejemplo.com LLAVE-SECRETA"}))
    with pytest.raises(ErrorEnvio) as e:
        cliente.enviar("ana@ejemplo.com", "a", "t", "h")
    assert "401" in str(e.value) and "LLAVE" not in str(e.value) and "ana@" not in str(e.value)


def test_brevo_traduce_un_timeout():
    def manejador(req):
        raise httpx.ConnectTimeout("lento")
    with pytest.raises(ErrorEnvio, match="ConnectTimeout"):
        _brevo(manejador).enviar("ana@ejemplo.com", "a", "t", "h")
