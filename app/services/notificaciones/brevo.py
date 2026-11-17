"""Cliente de correo con la API HTTP de Brevo (antes Sendinblue). Es el único módulo que la conoce.

Va por HTTPS (puerto 443): la VM de Azure bloquea el 25 de salida. Brevo permite verificar un
remitente individual sin tener dominio propio. Para cambiar de proveedor, otra clase como esta.
"""
from typing import Optional

import httpx

from app.services.notificaciones.base import ErrorEnvio


class BrevoCliente:
    def __init__(self, api_key: str, remitente: str, nombre_remitente: str, url: str,
                 timeout_s: float, cliente: Optional[httpx.Client] = None):
        self._api_key, self._remitente, self._nombre = api_key, remitente, nombre_remitente
        self._url, self._timeout = url, timeout_s
        self._cliente = cliente

    def enviar(self, destinatario: str, asunto: str, texto: str, html: str) -> None:
        carga = {"sender": {"name": self._nombre, "email": self._remitente},
                 "to": [{"email": destinatario}],
                 "subject": asunto, "textContent": texto, "htmlContent": html}
        cabeceras = {"api-key": self._api_key, "accept": "application/json"}
        try:
            if self._cliente is not None:
                r = self._cliente.post(self._url, json=carga, headers=cabeceras, timeout=self._timeout)
            else:
                r = httpx.post(self._url, json=carga, headers=cabeceras, timeout=self._timeout)
        except httpx.HTTPError as error:   # timeout, red, DNS
            raise ErrorEnvio(type(error).__name__) from error
        if r.status_code >= 400:
            # Solo el estado: el cuerpo de la respuesta podría repetir el correo del usuario
            raise ErrorEnvio(f"el proveedor respondió {r.status_code}")
