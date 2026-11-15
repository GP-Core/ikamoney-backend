"""Eliminar la cuenta y todos los datos del usuario (T56). Es irreversible.

El orden del borrado es explícito y no se deja solo al ON DELETE CASCADE: `gasto.categoria_id`
es RESTRICT, y en MySQL borrar solo `usuario` falla con el error 1451 si tiene un gasto en una
categoría propia. Por eso los gastos se van antes que las categorías. El borrado final de
`usuario` arrastra por cascada las tablas sin modelo aquí (p. ej. `resumen_mensual`).
Verificación en MySQL: docs/ELIMINAR_CUENTA.md.
"""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errores import ApiError, campo_error
from app.core.seguridad import verificar_contrasena
from app.models import (Categoria, Deuda, EstadoCuenta, Gasto, Ingreso, Movimiento, PlanMsi,
                        ScoreHistorial, Tarjeta, Usuario)
from app.schemas.cuenta import CuentaEliminar


def eliminar(db: Session, usuario: Usuario, datos: CuentaEliminar) -> None:
    # 403 y no 401: un 401 significa "sesión inválida" y el frontend cerraría la sesión.
    if not verificar_contrasena(datos.contrasena, usuario.contrasena_hash):
        raise ApiError(403, "CONTRASENA_INCORRECTA", "La contraseña no es correcta.",
                       [campo_error("contrasena", "No coincide con la de tu cuenta.")])

    uid = usuario.id
    tarjetas = select(Tarjeta.id).where(Tarjeta.usuario_id == uid)
    estados = select(EstadoCuenta.id).where(EstadoCuenta.tarjeta_id.in_(tarjetas))
    pasos = (
        delete(Gasto).where(Gasto.usuario_id == uid),
        delete(Ingreso).where(Ingreso.usuario_id == uid),
        delete(Movimiento).where(Movimiento.estado_cuenta_id.in_(estados)),
        delete(PlanMsi).where(PlanMsi.tarjeta_id.in_(tarjetas)),
        delete(EstadoCuenta).where(EstadoCuenta.tarjeta_id.in_(tarjetas)),
        delete(Tarjeta).where(Tarjeta.usuario_id == uid),
        delete(Deuda).where(Deuda.usuario_id == uid),
        delete(ScoreHistorial).where(ScoreHistorial.usuario_id == uid),
        delete(Categoria).where(Categoria.usuario_id == uid),   # las base (usuario_id NULL) se quedan
        delete(Usuario).where(Usuario.id == uid),
    )
    # Sin confirmar(): recalcular() guardaría un score nuevo del usuario que se está borrando.
    try:
        for paso in pasos:
            db.execute(paso.execution_options(synchronize_session=False))
        db.commit()
    except Exception:
        db.rollback()   # todo o nada: si un paso falla, no se borra nada
        raise
