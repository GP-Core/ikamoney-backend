"""GeminiCliente con un SDK falso y un reloj simulado: no hay red ni esperas reales."""
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.services.ia import IaNoDisponible
from app.services.ia.gemini import GeminiCliente


class Reloj:
    def __init__(self):
        self.ahora = 0.0

    def __call__(self):
        return self.ahora

    def dormir(self, segundos):
        self.ahora += segundos


class SdkFalso:
    """Imita genai.Client: cada llamada consume `dura` segundos y responde lo siguiente de la lista."""

    def __init__(self, reloj, *respuestas, dura=1.0):
        self.llamadas = []
        pendientes = list(respuestas)

        class Modelos:
            def generate_content(_, model, contents, config):
                self.llamadas.append(config.http_options.timeout)
                reloj.ahora += dura
                r = pendientes.pop(0) if len(pendientes) > 1 else pendientes[0]
                if isinstance(r, Exception):
                    raise r
                return SimpleNamespace(text=r)

        self.models = Modelos()


def _cliente(*respuestas, dura=1.0):
    reloj = Reloj()
    sdk = SdkFalso(reloj, *respuestas, dura=dura)
    return GeminiCliente("llave", "modelo", cliente=sdk, reloj=reloj, dormir=reloj.dormir), sdk, reloj


def _saturado():
    return errors.APIError(503, {"error": {"message": "saturado"}})


def test_responde_el_texto_y_manda_el_tope_en_milisegundos():
    cliente, sdk, _ = _cliente('{"ok": true}')
    assert cliente.generar_json("prompt", {}, limite_s=30) == '{"ok": true}'
    assert sdk.llamadas == [30000]


def test_reintenta_si_esta_saturado_sin_pasar_del_tope():
    cliente, sdk, reloj = _cliente(_saturado(), _saturado(), '{"ok": true}')
    assert cliente.generar_json("prompt", {}, limite_s=30) == '{"ok": true}'
    assert len(sdk.llamadas) == 3
    assert sdk.llamadas[1] < sdk.llamadas[0]          # cada intento recibe solo el tiempo que queda
    assert reloj.ahora <= 30


def test_se_rinde_al_agotar_el_tope():
    cliente, sdk, reloj = _cliente(_saturado(), dura=5.0)
    with pytest.raises(IaNoDisponible):
        cliente.generar_json("prompt", {}, limite_s=30)
    assert reloj.ahora <= 30


@pytest.mark.parametrize("falla", [errors.APIError(400, {"error": {"message": "x"}}),
                                   httpx.ReadTimeout("tardó")])
def test_errores_del_proveedor_son_ia_no_disponible(falla):
    cliente, sdk, _ = _cliente(falla)
    with pytest.raises(IaNoDisponible):
        cliente.generar_json("prompt", {}, limite_s=30)
    assert len(sdk.llamadas) == 1   # un 400 o un timeout no se reintentan


def test_el_error_explica_la_causa():
    falla = errors.APIError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                            "message": "API key not valid."}})
    cliente, _, _ = _cliente(falla)
    with pytest.raises(IaNoDisponible, match="400 INVALID_ARGUMENT: API key not valid"):
        cliente.generar_json("prompt", {}, limite_s=30)


def test_respuesta_vacia():
    cliente, _, _ = _cliente("")
    with pytest.raises(IaNoDisponible):
        cliente.generar_json("prompt", {}, limite_s=30)


def test_sin_llave_no_llama_a_nadie():
    with pytest.raises(IaNoDisponible):
        GeminiCliente("", "modelo").generar_json("prompt", {}, limite_s=30)
