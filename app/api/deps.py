"""Dependencias comunes de los routers, con alias para mantener las firmas cortas."""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.seguridad import usuario_actual
from app.models import Usuario

Db = Annotated[Session, Depends(get_db)]
UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]
