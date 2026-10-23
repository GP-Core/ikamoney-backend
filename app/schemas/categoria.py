"""Esquemas de /categorias (T17 §4.2)."""
from pydantic import BaseModel, Field

from app.schemas.base import Entrada


class CategoriaCrear(Entrada):
    nombre: str = Field(min_length=1, max_length=60)


class CategoriaOut(BaseModel):
    id: int
    nombre: str
    base: bool
