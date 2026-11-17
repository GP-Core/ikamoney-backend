from sqlalchemy.orm import Session

from app.models import Usuario


def recalcular(db: Session, usuario: Usuario):
    """Gancho de T17 §3 ('Recálculo'): cada alta, cambio o baja recalcula el score,
    el historial del mes y las alertas en la misma petición/transacción.

    Lo llama confirmar() después del flush y antes del commit, así que el score ve los cambios
    de la petición y su fila de historial se guarda en la misma transacción.
    Después del score revisa las alertas (T47); devuelve el resultado de esa revisión.
    """
    from app.services import alertas, score  # import aquí: score -> proyeccion -> ... evita ciclos

    score.guardar_en_historial(db, usuario)
    return alertas.revisar(db, usuario)