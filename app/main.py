from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.formparsers import MultiPartParser

from app.api.routes import (categorias, deudas, estados_cuenta, health, movimientos, msi,
                            proyeccion, tarjetas)
from app.core.config import settings
from app.core.errores import registrar_manejadores

# Starlette pasa a un archivo temporal en disco las partes de más de 1 MB. El PDF de un estado de
# cuenta debe quedarse en memoria (IS-02), así que el umbral se sube por encima del máximo permitido.
MultiPartParser.max_file_size = (settings.pdf_max_mb + 1) * 1024 * 1024

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
app.include_router(categorias.router, prefix="/api/v1")
app.include_router(movimientos.router, prefix="/api/v1")
app.include_router(proyeccion.router, prefix="/api/v1")
app.include_router(estados_cuenta.router, prefix="/api/v1")