"""Validación del archivo subido. El PDF se lee en memoria y el archivo se cierra siempre (IS-02)."""
from typing import BinaryIO, Optional

from app.core.errores import ApiError, campo_error

TIPO_PDF = "application/pdf"


def _invalido(mensaje: str) -> ApiError:
    return ApiError(422, "ARCHIVO_INVALIDO", mensaje + " Puedes capturar los datos a mano.",
                    [campo_error("archivo", mensaje)])


def leer(archivo: Optional[BinaryIO], tipo: Optional[str], max_bytes: int) -> bytes:
    """Bytes del PDF; ARCHIVO_INVALIDO si falta, no es PDF o pesa más de `max_bytes`.

    Cierra el archivo pase lo que pase, así no queda ninguna copia abierta del PDF.
    """
    try:
        if archivo is None:
            raise _invalido("Sube tu estado de cuenta en PDF.")
        if (tipo or "").split(";")[0].strip().lower() != TIPO_PDF:
            raise _invalido("El archivo debe ser un PDF.")
        contenido = archivo.read(max_bytes + 1)   # uno de más basta para saber si se pasa
        if len(contenido) > max_bytes:
            raise _invalido(f"El PDF no puede pesar más de {max_bytes // (1024 * 1024)} MB.")
        if not contenido.startswith(b"%PDF-"):
            raise _invalido("El archivo debe ser un PDF.")
        return contenido
    finally:
        if archivo is not None:
            archivo.close()
