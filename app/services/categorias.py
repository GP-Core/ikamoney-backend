"""Categorías: predefinidas del sistema (usuario_id NULL) y propias del usuario (T17 §4.2)."""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errores import ApiError, campo_error
from app.models import Categoria, Usuario
from app.schemas.categoria import CategoriaCrear, CategoriaOut


def _visibles(usuario: Usuario):
    return or_(Categoria.usuario_id == usuario.id, Categoria.usuario_id.is_(None))


def a_out(c: Categoria) -> CategoriaOut:
    return CategoriaOut(id=c.id, nombre=c.nombre, base=c.usuario_id is None)


def obtener_visible(db: Session, usuario: Usuario, categoria_id: int) -> Categoria:
    """Categoría base o propia; la de otro usuario se trata como inexistente (404)."""
    c = db.scalar(select(Categoria).where(Categoria.id == categoria_id, _visibles(usuario)))
    if c is None:
        raise ApiError(404, "CATEGORIA_NO_ENCONTRADA", "La categoría no existe.")
    return c


def listar(db: Session, usuario: Usuario) -> list[CategoriaOut]:
    filas = db.scalars(select(Categoria).where(_visibles(usuario))).all()
    filas = sorted(filas, key=lambda c: (c.usuario_id is not None, c.nombre.lower()))  # base primero
    return [a_out(c) for c in filas]


def crear(db: Session, usuario: Usuario, datos: CategoriaCrear) -> CategoriaOut:
    # MySQL no considera duplicados los NULL, así que se valida aquí (sin distinguir mayúsculas)
    existe = db.scalar(select(Categoria.id).where(
        _visibles(usuario), func.lower(Categoria.nombre) == datos.nombre.lower()))
    if existe is not None:
        raise ApiError(400, "CATEGORIA_DUPLICADA", "Ya existe una categoría con ese nombre.",
                       [campo_error("nombre", "Ya existe.")])
    c = Categoria(usuario_id=usuario.id, nombre=datos.nombre)
    db.add(c)
    db.commit()
    return a_out(c)
