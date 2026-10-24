"""Anonimización antes de llamar a la IA (IS-05), tomada de la PoC de T08.

Nunca se envía un texto donde el verificador encuentre un número de tarjeta o CLABE, un RFC de
persona física o una CURP. Las terminaciones enmascaradas (**** 1234) sí se permiten. El nombre
del titular no se detecta con patrones: se buscan los `terminos` (el nombre del usuario del token).
"""
import re

PATRONES = {
    # 16 a 18 dígitos (tarjeta y CLABE), aunque vengan con espacios o guiones.
    "tarjeta/CLABE": re.compile(r"\b(?:\d[ -]?){15,17}\d\b"),
    # RFC de persona física (13 caracteres). El de persona moral (12) es el del banco: no se marca.
    "RFC": re.compile(r"\b[A-ZÑ&]{4}\d{6}[A-Z\d]{3}\b"),
    "CURP": re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HMX][A-Z]{5}[A-Z\d]\d\b"),
}
MARCAS = {"tarjeta/CLABE": "[TARJETA_O_CLABE]", "RFC": "[RFC]", "CURP": "[CURP]"}
MARCA_PERSONAL = "[DATO_PERSONAL]"

# El banco puede imprimir el nombre con o sin acentos (JOSE / JOSÉ, MUNOZ / MUÑOZ)
_VARIANTES = {"a": "aáàäâ", "e": "eéèëê", "i": "iíìïî", "o": "oóòöô", "u": "uúùüû", "n": "nñ"}
_SIN_ACENTO = {c: base for base, variantes in _VARIANTES.items() for c in variantes}
# Palabras del nombre que también son comunes en un estado de cuenta: no se buscan solas
_PARTICULAS = {"de", "del", "la", "las", "los", "y", "san", "santa", "van", "von", "mc"}


class DatosSensiblesError(Exception):
    """El texto todavía trae datos personales: no se debe enviar."""


def _patron_termino(termino: str) -> re.Pattern:
    def letra(c: str) -> str:
        base = _SIN_ACENTO.get(c.lower())
        return f"[{_VARIANTES[base]}]" if base else re.escape(c)

    # El PDF puede partir un nombre en dos líneas: se acepta cualquier espacio entre palabras.
    palabras = r"\s+".join("".join(letra(c) for c in p) for p in termino.split())
    return re.compile(rf"(?<!\w){palabras}(?!\w)", re.IGNORECASE)


def terminos_del_nombre(nombre: str) -> list[str]:
    """El nombre completo y cada palabra de 3 letras o más (el banco puede omitir alguna)."""
    palabras = [p for p in nombre.split() if len(p) >= 3 and p.lower() not in _PARTICULAS]
    return [t for t in [nombre.strip(), *palabras] if t]


def limpiar_texto(texto: str, terminos=()) -> str:
    """Reemplaza tarjeta, CLABE, RFC, CURP y los `terminos` por marcas."""
    for termino in terminos:
        if termino.strip():
            texto = _patron_termino(termino).sub(MARCA_PERSONAL, texto)
    for tipo, patron in PATRONES.items():
        texto = patron.sub(MARCAS[tipo], texto)
    return texto


def verificar(texto: str, terminos=()) -> None:
    """Lanza DatosSensiblesError si encuentra un dato sensible. El mensaje nunca muestra el dato."""
    hallazgos = []
    for tipo, patron in PATRONES.items():
        for m in patron.finditer(texto):
            linea = texto.count("\n", 0, m.start()) + 1
            hallazgos.append(f"{tipo} en la línea {linea}")
    for termino in terminos:
        if termino.strip() and _patron_termino(termino).search(texto):
            hallazgos.append("el nombre del titular")
    if hallazgos:
        raise DatosSensiblesError("posibles datos sensibles: " + "; ".join(hallazgos[:10]))
