from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """El backend está vivo (no toca la base de datos)."""
    return {"status": "ok"}


@router.get("/ping-db")
def ping_db(db: Session = Depends(get_db)):
    """Prueba de la tubería: lee un mensaje de MySQL."""
    try:
        row = db.execute(
            text("SELECT message FROM pipeline_check ORDER BY id LIMIT 1")
        ).first()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="No se pudo consultar la base de datos")
    if row is None:
        raise HTTPException(status_code=404, detail="La tabla pipeline_check está vacía")
    return {"message": row[0]}