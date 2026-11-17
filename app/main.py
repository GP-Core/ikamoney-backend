from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartParser


from app.api.routes import (alertas, auth, categorias, deudas, cuenta, estados_cuenta, health,
                            internos, movimientos, msi, priorizador, proyeccion, score, simulador, tarjetas)
from app.core.config import settings
from app.core import cifrado
from app.core.errores import registrar_manejadores

# Starlette pasa a un archivo temporal en disco las partes de más de 1 MB. El PDF de un estado de
# cuenta debe quedarse en memoria (IS-02), así que el umbral se sube por encima del máximo permitido.
cifrado.verificar_llave()   # T53b: sin llave de cifrado la API no arranca

MultiPartParser.max_file_size = (settings.pdf_max_mb + 1) * 1024 * 1024

app = FastAPI(title="IKAMONEY API")
registrar_manejadores(app)  # errores con formato {codigo, mensaje, campos} (T17)

_RUTA_EXTRAER = "/api/v1/estados-cuenta/extraer"
_MARGEN_MULTIPART = 64 * 1024  # encabezados y bordes del formulario, además del archivo


@app.middleware("http")
async def limitar_subida_pdf(request: Request, call_next):
    """Rechaza por Content-Length un PDF demasiado grande antes de leer el cuerpo.

    Starlette pasa a un temporal en disco lo que excede MultiPartParser.max_file_size, y la ruta
    solo se entera después. Cortar aquí evita que un PDF de más de 11 MB toque el disco (IS-02).
    """
    if request.method == "POST" and request.url.path == _RUTA_EXTRAER:
        tope = (settings.pdf_max_mb + 1) * 1024 * 1024 + _MARGEN_MULTIPART
        declarado = request.headers.get("content-length", "")
        if declarado.isdigit() and int(declarado) > tope:
            return JSONResponse(status_code=422, content={
                "codigo": "ARCHIVO_INVALIDO",
                "mensaje": f"El PDF no puede pesar más de {settings.pdf_max_mb} MB. "
                           "Puedes capturar los datos a mano.",
                "campos": [{"campo": "archivo",
                            "mensaje": f"El PDF no puede pesar más de {settings.pdf_max_mb} MB."}]})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cada módulo nuevo registra su router aquí, siempre bajo /api
app.include_router(health.router, prefix="/api")
app.include_router(internos.router, prefix="/api")  # /api/internos/*: lo llama el cron con llave secreta
app.include_router(auth.router, prefix="/api")  # /api/auth/*: el frontend ya llama a estas rutas

# T17: los módulos de negocio van bajo /api/v1
app.include_router(tarjetas.router, prefix="/api/v1")
app.include_router(deudas.router, prefix="/api/v1")
app.include_router(msi.router, prefix="/api/v1")
app.include_router(categorias.router, prefix="/api/v1")
app.include_router(movimientos.router, prefix="/api/v1")
app.include_router(proyeccion.router, prefix="/api/v1")
app.include_router(estados_cuenta.router, prefix="/api/v1")
app.include_router(score.router, prefix="/api/v1")
app.include_router(cuenta.router, prefix="/api/v1")
app.include_router(simulador.router, prefix="/api/v1")
app.include_router(priorizador.router, prefix="/api/v1")
app.include_router(alertas.router, prefix="/api/v1")
