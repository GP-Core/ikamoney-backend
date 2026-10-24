"""¿El texto parece un estado de cuenta de tarjeta? Se revisa aquí, antes de enviar nada a la IA."""
import unicodedata

# Frases que aparecen en los estados de cuenta de tarjeta de crédito mexicanos
FRASES = ("estado de cuenta", "fecha de corte", "fecha limite de pago", "pago minimo",
          "limite de credito", "credito disponible", "pago para no generar intereses",
          "saldo anterior", "saldo al corte", "tasa de interes")
MIN_FRASES = 2


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos ni espacios (algunos PDF pegan las palabras: 'FECHADECORTE')."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", texto.lower())
                          if unicodedata.category(c) != "Mn")
    return "".join(sin_acentos.split())


def parece_estado_de_cuenta(texto: str) -> bool:
    normal = _normalizar(texto)
    return sum(1 for f in FRASES if _normalizar(f) in normal) >= MIN_FRASES
