"""Formato de error de T17 §3: siempre { codigo, mensaje, campos }."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str, campos: list[dict] | None = None):
        self.status, self.codigo, self.mensaje, self.campos = status, codigo, mensaje, campos or []


def campo_error(campo: str, mensaje: str) -> dict:
    return {"campo": campo, "mensaje": mensaje}


def _json(status: int, codigo: str, mensaje: str, campos: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"codigo": codigo, "mensaje": mensaje, "campos": campos or []})


_MENSAJES = {
    "missing": "Este campo es obligatorio.",
    "greater_than": "Debe ser mayor a {gt}.",
    "greater_than_equal": "Debe ser mayor o igual a {ge}.",
    "less_than_equal": "Debe ser menor o igual a {le}.",
    "less_than": "Debe ser menor a {lt}.",
    "string_too_short": "No puede estar vacío.",
    "string_too_long": "Máximo {max_length} caracteres.",
    "string_pattern_mismatch": "Formato no válido.",
    "decimal_max_places": "Máximo {decimal_places} decimales.",
    "decimal_max_digits": "Tiene demasiados dígitos.",
    "decimal_whole_digits": "Tiene demasiados dígitos.",
    "decimal_parsing": "Debe ser un número.",
    "int_parsing": "Debe ser un número entero.",
    "int_from_float": "Debe ser un número entero.",
    "bool_parsing": "Debe ser verdadero o falso.",
    "date_parsing": "Fecha no válida; usa AAAA-MM-DD.",
    "date_from_datetime_parsing": "Fecha no válida; usa AAAA-MM-DD.",
    "date_type": "Fecha no válida; usa AAAA-MM-DD.",
    "extra_forbidden": "Campo no permitido.",
    "literal_error": "Valor no permitido. Opciones: {expected}.",
    "enum": "Valor no permitido.",
    "json_invalid": "El cuerpo no es un JSON válido.",
}
_CAMPOS_MONTO = {"limite_credito", "saldo_actual", "pago_mensual"}


def _mensaje(e: dict) -> str:
    if e["type"] == "value_error":
        return str(e.get("ctx", {}).get("error", "Valor no válido."))
    plantilla = _MENSAJES.get(e["type"], "Valor no válido.")
    try:
        return plantilla.format(**(e.get("ctx") or {}))
    except (KeyError, IndexError):
        return plantilla


async def _validacion(_: Request, exc: RequestValidationError):
    campos, codigo, mensaje = [], "DATOS_INVALIDOS", "Hay datos inválidos."
    for e in exc.errors():
        loc = [str(p) for p in e["loc"] if p not in ("body", "query", "path")]
        campo = ".".join(loc)
        campos.append(campo_error(campo, _mensaje(e)))
        es_monto = loc and (loc[-1].startswith("monto") or loc[-1] in _CAMPOS_MONTO)
        if es_monto and codigo == "DATOS_INVALIDOS":
            if e["type"] == "greater_than":
                codigo, mensaje = "MONTO_INVALIDO", "El monto debe ser mayor a cero."
            elif e["type"] == "greater_than_equal":
                codigo, mensaje = "MONTO_INVALIDO", "El monto no puede ser negativo."
    return _json(422, codigo, mensaje, campos)


_CODIGOS_HTTP = {401: "NO_AUTENTICADO", 404: "NO_ENCONTRADO", 405: "METODO_NO_PERMITIDO"}


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        return _json(exc.status, exc.codigo, exc.mensaje, exc.campos)

    app.add_exception_handler(RequestValidationError, _validacion)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _json(exc.status_code, _CODIGOS_HTTP.get(exc.status_code, "ERROR"), str(exc.detail))

    @app.exception_handler(Exception)
    async def _inesperado(_: Request, exc: Exception):
        return _json(500, "ERROR_INTERNO", "Ocurrió un error inesperado.")
