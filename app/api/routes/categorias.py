"""Endpoints de categorías. Solo HTTP: la lógica vive en app/services/categorias.py."""
from fastapi import APIRouter

from app.api.deps import Db, UsuarioActual
from app.schemas.categoria import CategoriaCrear, CategoriaOut
from app.services import categorias as servicio

router = APIRouter(prefix="/categorias", tags=["Categorías"])


@router.get("", response_model=list[CategoriaOut],
            summary="Categorías predefinidas y las del usuario")
def listar(db: Db, usuario: UsuarioActual):
    return servicio.listar(db, usuario)


@router.post("", response_model=CategoriaOut, status_code=201, summary="Crea una categoría propia")
def crear(body: CategoriaCrear, db: Db, usuario: UsuarioActual):
    return servicio.crear(db, usuario, body)
