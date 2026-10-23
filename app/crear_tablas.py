"""Crea las tablas que falten y siembra las categorías base (idempotente):
    docker compose exec api python -m app.crear_tablas
"""
from sqlalchemy import select

from app import models  # noqa: F401  (registra los modelos en Base.metadata)
from app.core.database import Base, SessionLocal, engine
from app.models import Categoria

CATEGORIAS_BASE = ["Vivienda", "Alimentación", "Transporte", "Servicios", "Salud",
                   "Educación", "Entretenimiento", "Compras", "Otros"]  # T18 §5


def sembrar_categorias() -> None:
    with SessionLocal() as db:
        existentes = set(db.scalars(select(Categoria.nombre).where(Categoria.usuario_id.is_(None))))
        for nombre in CATEGORIAS_BASE:
            if nombre not in existentes:
                db.add(Categoria(usuario_id=None, nombre=nombre))
        db.commit()


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    sembrar_categorias()
    print("Tablas listas y categorías base sembradas.")
