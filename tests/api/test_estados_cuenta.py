"""POST /api/v1/estados-cuenta/extraer (T31), con un cliente de IA falso: nunca se llama a Gemini."""
import pytest
from sqlalchemy import func, select

from app.core.seguridad import crear_token
from app.main import app
from app.models import Gasto, PlanMsi, Tarjeta, Usuario
from app.services.estados_cuenta import privacidad
from app.services.ia import obtener_cliente_ia
from tests.conftest import TestSession
from tests.utilidades_ia import (LINEAS_ESTADO, SIN_TIEMPO, ClienteFalso, pdf_con_contrasena,
                                 pdf_minimo, respuesta)

URL = "/api/v1/estados-cuenta/extraer"


@pytest.fixture
def ia():
    """Instala un ClienteFalso como cliente de IA; la prueba puede cambiar sus respuestas."""
    falso = ClienteFalso()
    app.dependency_overrides[obtener_cliente_ia] = lambda: falso
    yield falso
    app.dependency_overrides.pop(obtener_cliente_ia, None)


@pytest.fixture
def ha():
    """Usuaria cuyo nombre aparece en el estado de cuenta (con acentos en la app, sin ellos en el PDF)."""
    with TestSession() as db:
        u = Usuario(nombre="Ana Lucía Pérez Muñoz", correo="ana@ejemplo.com", contrasena_hash="x")
        db.add(u)
        db.commit()
        return {"Authorization": f"Bearer {crear_token(u.id)}"}


def _subir(client, headers, contenido=None, tipo="application/pdf"):
    contenido = pdf_minimo(LINEAS_ESTADO) if contenido is None else contenido
    return client.post(URL, files={"archivo": ("estado.pdf", contenido, tipo)}, headers=headers)


def _codigo(r):
    return r.status_code, r.json()["codigo"]


def test_requiere_token(client, ia):
    assert _subir(client, {}).status_code == 401
    assert ia.prompts == []


def test_extrae_con_la_estructura_del_contrato(client, ha, ia):
    r = _subir(client, ha)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "tarjeta": {"banco": "Banco Ejemplo", "limiteCredito": 20000.0, "saldoActual": 3750.0,
                    "tasaAnual": 48.0, "pagoMinimo": 300.0, "pagoNoIntereses": 1250.0,
                    "diaCorte": 31, "diaLimitePago": 20},
        "msi": [{"descripcion": "TIENDA EJEMPLO", "montoTotal": 3000.0, "meses": 12,
                 "mensualidadesPagadas": 2}],
        # solo cargos: sin la mensualidad MSI ni el pago recibido
        "movimientos": [{"fecha": "2026-08-02", "concepto": "SUPERMERCADO EJEMPLO", "monto": 1000.0}],
    }


def test_datos_no_encontrados_van_en_null(client, ha, ia):
    ia._respuestas = [respuesta(banco=None, fecha_corte=None, fecha_limite_pago=None,
                                credito={"limite_credito": None, "credito_disponible": None},
                                pagos={"total_a_pagar_periodo": 3750.0, "pago_minimo": 300.0,
                                       "pago_para_no_generar_intereses": None,
                                       "pago_minimo_mas_msi": None})]
    tarjeta = _subir(client, ha).json()["tarjeta"]
    assert tarjeta["banco"] is None and tarjeta["limiteCredito"] is None
    assert tarjeta["diaCorte"] is None and tarjeta["diaLimitePago"] is None
    assert tarjeta["pagoNoIntereses"] is None
    assert set(tarjeta) == {"banco", "limiteCredito", "saldoActual", "tasaAnual", "pagoMinimo",
                            "pagoNoIntereses", "diaCorte", "diaLimitePago"}   # la llave no se omite


def test_cero_movimientos_no_es_error(client, ha, ia):
    ia._respuestas = [respuesta(movimientos=[])]
    r = _subir(client, ha)
    assert r.status_code == 200
    assert r.json()["msi"] == [] and r.json()["movimientos"] == []


def test_a_la_ia_no_llegan_nombre_ni_tarjeta(client, ha, ia):
    assert _subir(client, ha).status_code == 200
    enviado = ia.prompts[0]
    for dato in ("ANA", "LUCIA", "PEREZ", "MUNOZ", "5204", "9012"):
        assert dato not in enviado
    assert "[DATO_PERSONAL]" in enviado and "[TARJETA_O_CLABE]" in enviado


def test_no_guarda_nada_en_la_base(client, ha, ia):
    assert _subir(client, ha).status_code == 200
    with TestSession() as db:
        for modelo in (Tarjeta, PlanMsi, Gasto):
            assert db.scalar(select(func.count()).select_from(modelo)) == 0


@pytest.mark.parametrize("contenido,tipo", [
    (b"no soy un pdf", "text/plain"),                  # tipo equivocado
    (b"no soy un pdf", "application/pdf"),             # dice ser PDF, pero no lo es
    (b"%PDF-1.4" + b"0" * (10 * 1024 * 1024), "application/pdf"),   # más de 10 MB
])
def test_archivo_invalido(client, ha, ia, contenido, tipo):
    r = _subir(client, ha, contenido, tipo)
    assert _codigo(r) == (422, "ARCHIVO_INVALIDO")
    assert "a mano" in r.json()["mensaje"]
    assert ia.prompts == []


def test_sin_archivo(client, ha, ia):
    r = client.post(URL, headers=ha)
    assert _codigo(r) == (422, "ARCHIVO_INVALIDO")


@pytest.mark.parametrize("contenido", [
    pdf_con_contrasena(LINEAS_ESTADO),
    b"%PDF-1.4\nesto no es un PDF de verdad",
    pdf_minimo([]),                                    # sin texto, como un escaneo
], ids=["con_contrasena", "danado", "sin_texto"])
def test_pdf_protegido_o_ilegible(client, ha, ia, contenido):
    assert _codigo(_subir(client, ha, contenido)) == (400, "PDF_PROTEGIDO")
    assert ia.prompts == []


def test_no_es_estado_de_cuenta(client, ha, ia):
    r = _subir(client, ha, pdf_minimo(["Receta de enchiladas", "Tortillas, salsa verde y queso"]))
    assert _codigo(r) == (400, "NO_ES_ESTADO_DE_CUENTA")
    assert ia.prompts == []


def test_datos_sensibles_cancela_sin_llamar_a_la_ia(client, ha, ia, monkeypatch):
    # Si la limpieza fallara, el verificador debe detener el envío
    monkeypatch.setattr(privacidad, "limpiar_texto", lambda texto, terminos=(): texto)
    assert _codigo(_subir(client, ha)) == (400, "DATOS_SENSIBLES")
    assert ia.prompts == []


def test_ia_no_disponible_por_timeout(client, ha, ia, caplog):
    ia._respuestas = [SIN_TIEMPO]
    r = _subir(client, ha)
    assert _codigo(r) == (503, "IA_NO_DISPONIBLE")
    assert "a mano" in r.json()["mensaje"] and "tiempo" not in r.json()["mensaje"]
    assert "se agotó el tiempo" in caplog.text   # la causa real queda en los logs, no en la respuesta


def test_ia_no_disponible_por_json_malformado(client, ha, ia):
    ia._respuestas = ["esto no es JSON"]
    assert _codigo(_subir(client, ha)) == (503, "IA_NO_DISPONIBLE")
    assert len(ia.prompts) == 4   # 1 intento + 3 reintentos


def test_reintenta_un_json_invalido(client, ha, ia):
    ia._respuestas = ['{"banco": "x"}', respuesta()]   # falta casi todo: no cumple el esquema
    assert _subir(client, ha).status_code == 200
    assert len(ia.prompts) == 2


def test_rechaza_llaves_extra_de_la_ia(client, ha, ia):
    ia._respuestas = [respuesta(titular="ANA LUCIA PEREZ")]
    assert _codigo(_subir(client, ha)) == (503, "IA_NO_DISPONIBLE")
