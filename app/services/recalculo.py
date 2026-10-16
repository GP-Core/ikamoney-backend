from sqlalchemy.orm import Session

from app.models import Usuario


def recalcular(db: Session, usuario: Usuario) -> None:
    """Gancho de T17 §3 ('Recálculo'): cada alta, cambio o baja recalcula el score,
    el historial del mes y las alertas en la misma petición/transacción.

    Aún no existen esos módulos (T35, T47...). Los endpoints ya llaman a esta función
    antes del commit; cuando el motor de cálculo esté listo, solo se implementa aquí.
    """
    return None
