from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import deudas, health, msi, tarjetas
from app.core.config import settings
from app.core.errores import registrar_manejadores

app = FastAPI(title="IKAMONEY API")
registrar_manejadores(app)  # errores con formato {codigo, mensaje, campos} (T17)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cada módulo nuevo registra su router aquí, siempre bajo /api
app.include_router(health.router, prefix="/api")

# T17: los módulos de negocio van bajo /api/v1
app.include_router(tarjetas.router, prefix="/api/v1")
app.include_router(deudas.router, prefix="/api/v1")
app.include_router(msi.router, prefix="/api/v1")