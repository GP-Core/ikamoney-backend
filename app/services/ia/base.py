"""Contrato del cliente de IA (T17 §11, reúso): cambiar de proveedor es escribir otra clase que
cumpla `ClienteIA`, sin tocar el servicio de estados de cuenta."""
from typing import Protocol


class IaNoDisponible(Exception):
    """La IA no respondió a tiempo, falló o no está configurada."""


class ClienteIA(Protocol):
    def generar_json(self, prompt: str, esquema: dict, limite_s: float) -> str:
        """Texto JSON que responde la IA a `prompt`, siguiendo `esquema`.

        Debe terminar en `limite_s` segundos como máximo (reintentos incluidos) y lanzar
        IaNoDisponible ante un timeout, una falla del proveedor o una respuesta vacía.
        """
        ...
