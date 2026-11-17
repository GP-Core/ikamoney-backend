"""Envío de alertas fuera de la app (T50): correo primero, push después.

Reglas:
  * Solo se envía lo que el usuario dejó activo en su configuración (canal_correo).
  * Una alerta se avisa una sola vez (`notificada_en`); lo que falla se reintenta en la revisión diaria
    mientras no pasen `ventana_aviso_horas` desde que se disparó.
  * Un fallo del proveedor nunca rompe la escritura del usuario ni la revisión de los demás.
  * Un solo correo por revisión, con todas las alertas nuevas.
  * Sin saldos en ningún texto (IC-07): ver plantillas.py.
"""
import logging
from datetime import timedelta
from functools import lru_cache
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Alerta, Usuario
from app.services.alertas_reglas import reglas_vigentes
from app.services.notificaciones import plantillas
from app.services.notificaciones.base import ClienteCorreo, ErrorEnvio

__all__ = ["ClienteCorreo", "ErrorEnvio", "cliente_correo", "enviar_pendientes"]
log = logging.getLogger(__name__)


@lru_cache
def cliente_correo() -> Optional[ClienteCorreo]:
    """Cliente compartido, o None si no hay llave configurada (entonces no se envía nada)."""
    if not settings.correo_api_key or not settings.correo_remitente:
        return None
    from app.services.notificaciones.brevo import BrevoCliente
    return BrevoCliente(api_key=settings.correo_api_key, remitente=settings.correo_remitente,
                        nombre_remitente=settings.correo_remitente_nombre, url=settings.correo_url,
                        timeout_s=settings.correo_timeout_s)


def pendientes(db: Session, usuario: Usuario) -> list[Alerta]:
    from app.services import alertas
    desde = alertas.ahora() - timedelta(hours=reglas_vigentes().ventana_aviso_horas)
    return list(db.scalars(select(Alerta).where(
        Alerta.usuario_id == usuario.id, Alerta.estado == "activa",
        Alerta.notificada_en.is_(None), Alerta.disparada_en >= desde)
        .order_by(Alerta.disparada_en, Alerta.id)))


def enviar_pendientes(db: Session, usuario: Usuario) -> int:
    """Manda por correo las alertas activas sin avisar. Devuelve cuántas alertas se avisaron.

    Hace commit al marcarlas. No lanza: cualquier falla se registra (sin contenido) y se reintenta
    en la siguiente revisión diaria.
    """
    try:
        from app.services import alertas
        if not alertas.config_efectiva(db, usuario).canal_correo:
            return 0
        cliente = cliente_correo()
        lista = pendientes(db, usuario) if cliente is not None else []
        if not lista:
            return 0
        enlace = f"{settings.frontend_url.rstrip('/')}/alertas"
        asunto, texto, html = plantillas.armar(usuario.nombre, lista, enlace)
        cliente.enviar(usuario.correo, asunto, texto, html)
        momento = alertas.ahora()
        for a in lista:
            a.notificada_en = momento
        db.commit()
        return len(lista)
    except ErrorEnvio as error:
        db.rollback()
        log.warning("No se pudo enviar el correo de alertas del usuario %s: %s", usuario.id, error)
    except Exception:   # noqa: BLE001 — avisar es secundario: no debe romper lo que lo disparó
        db.rollback()
        log.exception("Falló el envío de alertas del usuario %s", usuario.id)
    return 0
