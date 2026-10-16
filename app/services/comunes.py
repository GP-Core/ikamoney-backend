"""Utilidades de acceso a datos compartidas por todos los servicios."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import ApiError
from app.models import Usuario
from app.services.recalculo import recalcular


def obtener_del_usuario(db: Session, modelo, id_: int, usuario: Usuario, error: ApiError):
    """Registro del usuario por id; inexistente o de otro usuario => `error` (404, T17 §3)."""
    obj = db.scalar(select(modelo).where(modelo.id == id_, modelo.usuario_id == usuario.id))
    if obj is None:
        raise error
    return obj


def confirmar(db: Session, usuario: Usuario) -> None:
    """Cierre común de toda escritura: envía los cambios, recalcula (T17 §3) y confirma."""
    db.flush()
    recalcular(db, usuario)
    db.commit()
