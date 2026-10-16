from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errores import ApiError, campo_error
from app.core.seguridad import usuario_actual
from app.models import Categoria, Usuario
from app.schemas.flujo import CategoriaCrear, CategoriaOut

router = APIRouter(prefix="/categorias", tags=["Categorías"])


def _out(c: Categoria) -> CategoriaOut:
    return CategoriaOut(id=c.id, nombre=c.nombre, base=c.usuario_id is None)


@router.get("", response_model=list[CategoriaOut],
            summary="Categorías predefinidas y las del usuario")
def listar(db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    filas = db.scalars(select(Categoria).where(
        or_(Categoria.usuario_id == usuario.id, Categoria.usuario_id.is_(None)))).all()
    filas = sorted(filas, key=lambda c: (c.usuario_id is not None, c.nombre.lower()))  # base primero
    return [_out(c) for c in filas]


@router.post("", response_model=CategoriaOut, status_code=201, summary="Crea una categoría propia")
def crear(body: CategoriaCrear, db: Session = Depends(get_db),
          usuario: Usuario = Depends(usuario_actual)):
    # MySQL no considera duplicados los NULL, así que se valida aquí (sin distinguir mayúsculas)
    existe = db.scalar(select(Categoria.id).where(
        or_(Categoria.usuario_id == usuario.id, Categoria.usuario_id.is_(None)),
        func.lower(Categoria.nombre) == body.nombre.lower()))
    if existe is not None:
        raise ApiError(400, "CATEGORIA_DUPLICADA", "Ya existe una categoría con ese nombre.",
                       [campo_error("nombre", "Ya existe.")])
    c = Categoria(usuario_id=usuario.id, nombre=body.nombre)
    db.add(c)
    db.commit()
    return _out(c)
