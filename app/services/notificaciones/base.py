"""Contrato del cliente de correo (T50): cambiar de proveedor es escribir otra clase que cumpla
`ClienteCorreo` y devolverla en `cliente_correo()`, sin tocar el envío de alertas."""
from typing import Protocol


class ErrorEnvio(Exception):
    """El proveedor no aceptó el correo, no respondió a tiempo o no está configurado.

    El mensaje describe la causa técnica (estado HTTP, tipo de error); nunca trae el contenido
    del correo ni la llave del proveedor.
    """


class ClienteCorreo(Protocol):
    def enviar(self, destinatario: str, asunto: str, texto: str, html: str) -> None:
        """Envía un correo; lanza ErrorEnvio si no salió."""
        ...
