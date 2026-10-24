"""Cliente de Gemini (decisión de T07). Es el único módulo que conoce a google-genai.

La llave vive solo en el servidor (AI_API_KEY, IS-07 / IC-13). El SDK no reintenta por su cuenta:
los reintentos por saturación los hace este cliente para que el tope de `limite_s` sea el total
de la llamada, no el de cada intento (IS-04).
"""
import time
from typing import Callable, Optional

from google import genai
from google.genai import errors, types

from app.services.ia.base import IaNoDisponible

CODIGOS_SATURACION = {408, 429, 500, 502, 503, 504}
ESPERA_INICIAL_S = 2.0
MIN_INTENTO_S = 2.0   # con menos tiempo restante ya no vale la pena otro intento


class GeminiCliente:
    def __init__(self, api_key: str, modelo: str, cliente=None,
                 reloj: Callable[[], float] = time.monotonic,
                 dormir: Callable[[float], None] = time.sleep):
        self._api_key, self._modelo = api_key, modelo
        self._cliente: Optional[genai.Client] = cliente   # se crea al primer uso
        self._reloj, self._dormir = reloj, dormir

    def _sdk(self) -> genai.Client:
        if self._cliente is None:
            if not self._api_key:
                raise IaNoDisponible("falta AI_API_KEY")
            self._cliente = genai.Client(api_key=self._api_key)
        return self._cliente

    def generar_json(self, prompt: str, esquema: dict, limite_s: float) -> str:
        fin = self._reloj() + limite_s
        espera = ESPERA_INICIAL_S
        while True:
            restante = fin - self._reloj()
            if restante < MIN_INTENTO_S:
                raise IaNoDisponible("se agotó el tiempo de espera")
            ajustes = types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=esquema,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                http_options=types.HttpOptions(timeout=int(restante * 1000)),  # en milisegundos
            )
            try:
                respuesta = self._sdk().models.generate_content(
                    model=self._modelo, contents=prompt, config=ajustes)
            except errors.APIError as error:
                # Saturado: esperar cada vez más y reintentar, sin pasar del tope
                if error.code in CODIGOS_SATURACION and fin - self._reloj() > espera + MIN_INTENTO_S:
                    self._dormir(espera)
                    espera *= 2
                    continue
                # p. ej. "Gemini respondió 400 INVALID_ARGUMENT: API key not valid" (nunca trae la llave)
                raise IaNoDisponible(f"Gemini respondió {error.code} {error.status}: {error.message}") from error
            except IaNoDisponible:
                raise
            except Exception as error:  # timeout o falla de red (httpx)
                raise IaNoDisponible(type(error).__name__) from error
            if not respuesta.text:
                raise IaNoDisponible("respuesta vacía")
            return respuesta.text
