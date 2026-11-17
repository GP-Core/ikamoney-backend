"""POST /api/v1/estados-cuenta/extraer (T31), con un cliente de IA falso: nunca se llama a Gemini."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.seguridad import crear_token
from app.main import app
from app.models import Gasto, PlanMsi, Tarjeta, Usuario
from app.services.estados_cuenta import privacidad
from app.services.ia import IaNoDisponible, obtener_cliente_ia
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
    pytest.param(b"no soy un pdf", "text/plain", id="tipo_equivocado"),
    pytest.param(b"no soy un pdf", "application/pdf", id="no_es_pdf"),      # dice ser PDF, pero no lo es
    pytest.param(b"%PDF-1.4" + b"0" * (10 * 1024 * 1024), "application/pdf", id="mas_de_10_mb"),
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


# ---------------------------------------------------------------- T53(a): borrado del PDF (IS-02, RN-03)
# En cada camino, éxito o error: el archivo se cierra, no pasa a un temporal en disco, no se guarda
# nada en la base y el texto del PDF no aparece en los logs.
MARCA = "MARCA-DISTINTIVA-DEL-PDF-7731"
TABLAS = (Tarjeta, PlanMsi, Gasto)


def _espiar_archivo(monkeypatch):
    """Registra el archivo que recibe archivo.leer() para comprobar después que quedó cerrado."""
    from app.services.estados_cuenta import archivo as modulo
    vistos = []
    original = modulo.leer

    def espia(f, tipo, max_bytes):
        vistos.append(f)
        return original(f, tipo, max_bytes)

    monkeypatch.setattr(modulo, "leer", espia)
    return vistos


def _sin_rastros(vistos, caplog):
    assert vistos and all(f.closed for f in vistos)
    assert not any(getattr(f, "_rolled", False) for f in vistos)   # nunca pasó a un temporal en disco
    assert MARCA not in caplog.text
    with TestSession() as db:
        from app.models import EstadoCuenta, Movimiento
        for modelo in (*TABLAS, EstadoCuenta, Movimiento):
            assert db.scalar(select(func.count()).select_from(modelo)) == 0


CAMINOS = {
    "exito": (None, None),
    "archivo_invalido": (b"no soy un pdf", None),
    "pdf_con_contrasena": (pdf_con_contrasena([MARCA, *LINEAS_ESTADO]), None),
    "pdf_danado": (b"%PDF-1.4\n" + MARCA.encode(), None),
    "no_es_estado": (pdf_minimo([MARCA, "Receta de enchiladas"]), None),
    "ia_sin_tiempo": (None, [SIN_TIEMPO]),
    "ia_caida": (None, [IaNoDisponible("Gemini respondió 503 UNAVAILABLE")]),
    "json_invalido": (None, ["esto no es JSON"]),
}


@pytest.mark.parametrize("contenido,respuestas", CAMINOS.values(), ids=CAMINOS.keys())
def test_el_pdf_no_deja_rastros_en_ningun_camino(client, ha, ia, monkeypatch, caplog,
                                                 contenido, respuestas):
    vistos = _espiar_archivo(monkeypatch)
    if respuestas:
        ia._respuestas = respuestas
    if contenido is None:
        contenido = pdf_minimo([MARCA, *LINEAS_ESTADO])
    _subir(client, ha, contenido)
    _sin_rastros(vistos, caplog)


def test_el_pdf_no_deja_rastros_si_falla_algo_inesperado(ha, ia, monkeypatch, caplog):
    vistos = _espiar_archivo(monkeypatch)
    ia._respuestas = [RuntimeError("falla interna con detalles")]
    cliente = TestClient(app, raise_server_exceptions=False)
    r = _subir(cliente, ha, pdf_minimo([MARCA, *LINEAS_ESTADO]))
    assert _codigo(r) == (500, "ERROR_INTERNO")
    assert "falla interna" not in r.text and "Traceback" not in r.text
    _sin_rastros(vistos, caplog)


def test_un_pdf_enorme_se_rechaza_antes_de_leer_el_cuerpo(client, ha, ia, monkeypatch):
    """Más de 11 MB: la respuesta sale del Content-Length, sin que Starlette cree un temporal."""
    from starlette import formparsers
    creados = []
    original = formparsers.MultiPartParser.__init__

    def espia(self, *a, **k):
        creados.append(1)
        original(self, *a, **k)

    monkeypatch.setattr(formparsers.MultiPartParser, "__init__", espia)
    r = _subir(client, ha, b"%PDF-1.4" + b"0" * (13 * 1024 * 1024))
    assert _codigo(r) == (422, "ARCHIVO_INVALIDO")
    assert "a mano" in r.json()["mensaje"]
    assert creados == [] and ia.prompts == []
