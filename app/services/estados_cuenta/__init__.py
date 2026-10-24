"""Carga y extracción de estados de cuenta con IA (T31, US 6.3).

Flujo de T17: validar el archivo -> leer el PDF a texto en memoria -> ¿es un estado de cuenta?
-> anonimizar y verificar -> IA con tope de 30 s -> validar el JSON -> responder. El PDF se cierra
siempre y nada se guarda en la base: el guardado ocurre solo cuando el usuario confirma (RN-08).
"""
import logging
import time
from typing import BinaryIO, Optional

from pydantic import ValidationError

from app.core.config import settings
from app.core.errores import ApiError
from app.models import Usuario
from app.schemas.estado_cuenta import EstadoCuentaExtraidoOut
from app.services.estados_cuenta import archivo, deteccion, pdf, privacidad
from app.services.estados_cuenta.conversion import a_contrato
from app.services.estados_cuenta.esquema_ia import EstadoCuentaIA, esquema_json
from app.services.estados_cuenta.prompt import armar_prompt
from app.services.ia import ClienteIA, IaNoDisponible

log = logging.getLogger(__name__)
MANUAL = " Puedes capturar los datos a mano."
_MIN_INTENTO_S = 2.0


def _error(status: int, codigo: str, mensaje: str) -> ApiError:
    return ApiError(status, codigo, mensaje + MANUAL)


def _consultar_ia(cliente: ClienteIA, prompt: str) -> EstadoCuentaIA:
    """Respuesta de la IA ya validada. Reintenta un JSON inválido mientras quede tiempo del tope."""
    fin = time.monotonic() + settings.ia_limite_s
    esquema = esquema_json()
    for _ in range(1 + settings.ia_reintentos_json):
        restante = fin - time.monotonic()
        if restante < _MIN_INTENTO_S:
            break
        texto = cliente.generar_json(prompt, esquema, restante)
        try:
            return EstadoCuentaIA.model_validate_json(texto, strict=True)
        except ValidationError:
            continue
    raise IaNoDisponible("la IA no devolvió un JSON válido")


def extraer(usuario: Usuario, contenido: Optional[BinaryIO], tipo: Optional[str],
            cliente: ClienteIA) -> EstadoCuentaExtraidoOut:
    datos_pdf = archivo.leer(contenido, tipo, settings.pdf_max_mb * 1024 * 1024)  # ya cerrado
    try:
        texto = pdf.leer_texto(datos_pdf)
    except pdf.PdfIlegible:
        raise _error(400, "PDF_PROTEGIDO", "No pudimos leer el PDF: tiene contraseña, está dañado "
                                           "o es una imagen escaneada.")
    finally:
        del datos_pdf   # solo se conserva el texto, que se limpia enseguida

    if not deteccion.parece_estado_de_cuenta(texto):
        raise _error(400, "NO_ES_ESTADO_DE_CUENTA",
                     "El archivo no parece un estado de cuenta de tarjeta de crédito.")

    terminos = privacidad.terminos_del_nombre(usuario.nombre)
    texto = privacidad.limpiar_texto(texto, terminos)
    try:
        privacidad.verificar(texto, terminos)
    except privacidad.DatosSensiblesError:
        raise _error(400, "DATOS_SENSIBLES", "Por tu seguridad no procesamos este archivo: no "
                                             "pudimos ocultar todos tus datos personales.")

    try:
        estado = _consultar_ia(cliente, armar_prompt(texto))
    except IaNoDisponible as error:
        # El usuario ve un mensaje genérico; la causa real queda en los logs (docker compose logs api)
        log.warning("IA no disponible: %s", error)
        raise _error(503, "IA_NO_DISPONIBLE", "La lectura automática no está disponible en este "
                                              "momento. Intenta de nuevo en unos minutos.")
    return a_contrato(estado)
