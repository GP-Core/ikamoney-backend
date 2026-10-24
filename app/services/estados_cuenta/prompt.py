"""Prompt de la PoC de T08 (prompt.txt, sin cambios) con el esquema y el texto ya limpio."""
import json
from functools import lru_cache
from pathlib import Path

from app.services.estados_cuenta.esquema_ia import esquema_json


@lru_cache
def _plantilla() -> str:
    return Path(__file__).with_name("prompt.txt").read_text(encoding="utf-8")


def armar_prompt(texto_limpio: str) -> str:
    esquema = json.dumps(esquema_json(), ensure_ascii=False, separators=(",", ":"))
    return _plantilla().replace("{ESQUEMA_JSON}", esquema).replace("{TEXTO}", texto_limpio)
