"""Cifrado de campos sensibles en reposo (T53b, IC-14, RNF-19): AES-256-GCM.

Qué se cifra y por qué está en docs/CIFRADO.md. Aquí vive la mecánica:

  * Llave de 32 bytes en la variable de entorno CIFRADO_LLAVE (base64). Sin ella la API no arranca.
  * Cada valor se guarda como  v1:<base64(nonce ‖ texto cifrado ‖ etiqueta)>  con un nonce aleatorio
    de 12 bytes: el mismo monto da un resultado distinto cada vez.
  * El "contexto" (tabla.columna) va como dato autenticado: un valor copiado a otra columna no descifra.
  * El prefijo `v1:` identifica la versión, para poder rotar la llave o el formato más adelante.
  * Un valor SIN prefijo se lee como número en claro. Es lo que deja la migración a medias, y hace que
    se pueda repetir o revertir sin perder nada.

Lo cifrado no se puede filtrar, ordenar ni sumar en SQL: todo cálculo sobre estos campos se hace en
Python (hoy ya es así: proyección, score y priorizador).
"""
import base64
import binascii
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import String, TypeDecorator

from app.core.config import settings

PREFIJO = "v1:"
LONGITUD_COLUMNA = 96          # v1: + base64(12 + 13 + 16) = 59 caracteres como máximo
_CENTAVO = Decimal("0.01")
_MAXIMO = Decimal("9999999999.99")   # DECIMAL(12,2): lo que ya aceptaba la base

# (tabla, columna, admite NULL, valor por defecto del DDL original) — fuente única para modelos,
# migración y pruebas. `ingreso.monto` y `gasto.monto` quedan fuera a propósito (docs/CIFRADO.md).
COLUMNAS_CIFRADAS = (
    ("tarjeta", "limite_credito", False, None),
    ("tarjeta", "saldo_actual", False, "0"),
    ("deuda", "monto_original", False, None),
    ("deuda", "saldo_actual", False, None),
    ("deuda", "pago_mensual", True, None),
    ("plan_msi", "monto_original", False, None),
    ("plan_msi", "monto_mensualidad", False, None),
    ("estado_cuenta", "saldo_al_corte", False, None),
    ("estado_cuenta", "pago_minimo", True, None),
    ("estado_cuenta", "pago_no_intereses", True, None),
    ("movimiento", "monto", False, None),
    ("movimiento", "monto_extraido", True, None),
)


class ErrorCifrado(Exception):
    """Llave ausente o inválida, o un valor que no se pudo descifrar (llave equivocada o dato alterado)."""


def _decodificar_llave(valor: str) -> bytes:
    limpio = (valor or "").strip().replace("+", "-").replace("/", "_")
    try:
        llave = base64.urlsafe_b64decode(limpio + "=" * (-len(limpio) % 4))
    except (binascii.Error, ValueError):
        raise ErrorCifrado("CIFRADO_LLAVE no es base64 válido.") from None
    if len(llave) != 32:
        raise ErrorCifrado(f"CIFRADO_LLAVE debe medir 32 bytes (AES-256); mide {len(llave)}.")
    return llave


@lru_cache
def _aes(llave_b64: str) -> AESGCM:
    return AESGCM(_decodificar_llave(llave_b64))


def verificar_llave() -> None:
    """Se llama al arrancar la API: sin llave válida no se atiende nada, para no guardar en claro."""
    if not settings.cifrado_llave:
        raise ErrorCifrado(
            "Falta CIFRADO_LLAVE. Genera una con: python -c \"import secrets,base64;"
            "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())\" "
            "y guárdala en el .env (y aparte del respaldo de la base).")
    _aes(settings.cifrado_llave)


def cifrar_texto(texto: str, contexto: str) -> str:
    verificar_llave()
    nonce = os.urandom(12)
    cifrado = _aes(settings.cifrado_llave).encrypt(nonce, texto.encode(), contexto.encode())
    return PREFIJO + base64.b64encode(nonce + cifrado).decode()


def descifrar_texto(valor: str, contexto: str) -> str:
    verificar_llave()
    try:
        crudo = base64.b64decode(valor[len(PREFIJO):], validate=True)
        return _aes(settings.cifrado_llave).decrypt(crudo[:12], crudo[12:], contexto.encode()).decode()
    except (InvalidTag, binascii.Error, ValueError):
        # Nunca se incluye el valor ni el texto: solo dónde falló
        raise ErrorCifrado(f"No se pudo descifrar un valor de {contexto}: llave equivocada "
                           "o dato alterado.") from None


def a_decimal(valor, contexto: str) -> Decimal:
    """Lee lo que hay en la columna: texto cifrado, número en claro (texto o DECIMAL) o nada."""
    if isinstance(valor, str) and valor.startswith(PREFIJO):
        valor = descifrar_texto(valor, contexto)
    try:
        return Decimal(str(valor)).quantize(_CENTAVO, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ErrorCifrado(f"Valor no numérico en {contexto}.") from None


def a_texto(valor, contexto: str) -> str:
    """Decimal en la representación que se cifra: '1234.50', sin notación científica."""
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError(f"{contexto}: no es un número.") from None
    if not d.is_finite() or abs(d) > _MAXIMO:
        raise ValueError(f"{contexto}: monto fuera de rango.")
    return format(d.quantize(_CENTAVO, rounding=ROUND_HALF_UP), "f")


class DineroCifrado(TypeDecorator):
    """Monto (Decimal) guardado cifrado en una columna de texto. Los servicios siguen viendo Decimal."""
    impl = String(LONGITUD_COLUMNA)
    cache_ok = True

    def __init__(self, contexto: str):
        super().__init__()
        self.contexto = contexto

    def process_bind_param(self, valor, dialect):
        if valor is None:
            return None
        return cifrar_texto(a_texto(valor, self.contexto), self.contexto)

    def process_result_value(self, valor, dialect):
        if valor is None:
            return None
        return a_decimal(valor, self.contexto)


def dinero_cifrado(tabla: str, columna: str) -> DineroCifrado:
    return DineroCifrado(f"{tabla}.{columna}")
