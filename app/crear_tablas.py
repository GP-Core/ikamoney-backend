"""Crea las tablas que falten (idempotente):
    docker compose exec api python -m app.crear_tablas
"""
from app import models  # noqa: F401  (registra los modelos en Base.metadata)
from app.core.database import Base, engine

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print("Tablas listas.")
