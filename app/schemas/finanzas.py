"""Esquemas de entrada/salida. Aquí viven las validaciones de un solo campo (T18 §5);
las que cruzan campos (p. ej. coherencia de MSI) están en los routers para responder
con un código de error específico."""
from datetime import date
from decimal import Decimal
from typing import Annotated, ClassVar, Literal, Optional

from pydantic import (BaseModel, ConfigDict, Field, PlainSerializer,
                      model_validator)

from app.core.config import settings

_a_float = PlainSerializer(lambda v: float(v), return_type=float, when_used="json")

# DECIMAL(12,2) / DECIMAL(5,2). En el JSON de salida salen como número (T17: "2 decimales").
Dinero = Annotated[Decimal, Field(max_digits=12, decimal_places=2), _a_float]
Tasa = Annotated[Decimal, Field(max_digits=5, decimal_places=2), _a_float]
Dia = Annotated[int, Field(ge=1, le=31)]

TipoDeuda = Literal["prestamo_personal", "credito_auto", "credito_hipotecario",
                    "familiar_amigo", "otro"]


class _Entrada(BaseModel):
    # extra="forbid": un campo que no existe (p. ej. usuario_id o un número de tarjeta
    # completo) se rechaza con 422 en vez de ignorarse en silencio.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Edicion(_Entrada):
    """PUT parcial: solo se cambian los campos enviados."""
    NO_NULOS: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _validar_envio(self):
        if not self.model_fields_set:
            raise ValueError("Envía al menos un campo para editar.")
        for campo in self.NO_NULOS:
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"'{campo}' no puede ser nulo.")
        return self


class EliminadoOut(BaseModel):
    id: int
    eliminado: bool = True


# ----------------------------------------------------------------- tarjeta
class TarjetaCrear(_Entrada):
    nombre: str = Field(min_length=1, max_length=60)
    banco: str = Field(min_length=1, max_length=60)
    ultimos_4: Optional[str] = Field(default=None, pattern=r"^[0-9]{4}$")  # nunca el número completo
    limite_credito: Dinero = Field(ge=0)
    saldo_actual: Dinero = Field(default=Decimal("0.00"), ge=0)
    dia_corte: Dia
    dia_pago: Dia
    tasa_anual: Optional[Tasa] = Field(default=None, ge=0, le=Decimal("999.99"))
    activa: bool = True


class TarjetaEditar(_Edicion):
    NO_NULOS = ("nombre", "banco", "limite_credito", "saldo_actual", "dia_corte", "dia_pago", "activa")
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=60)
    banco: Optional[str] = Field(default=None, min_length=1, max_length=60)
    ultimos_4: Optional[str] = Field(default=None, pattern=r"^[0-9]{4}$")
    limite_credito: Optional[Dinero] = Field(default=None, ge=0)
    saldo_actual: Optional[Dinero] = Field(default=None, ge=0)
    dia_corte: Optional[Dia] = None
    dia_pago: Optional[Dia] = None
    tasa_anual: Optional[Tasa] = Field(default=None, ge=0, le=Decimal("999.99"))
    activa: Optional[bool] = None


class TarjetaOut(BaseModel):
    id: int
    nombre: str
    banco: str
    ultimos_4: Optional[str]
    limite_credito: Dinero
    saldo_actual: Dinero
    credito_disponible: Dinero            # derivado
    porcentaje_limite_usado: float        # derivado (saldo / límite × 100)
    dia_corte: int
    dia_pago: int
    tasa_anual: Optional[Tasa]
    activa: bool
    proxima_fecha_corte: date             # derivada de dia_corte
    proxima_fecha_pago: date              # del estado de cuenta si existe; si no, de dia_pago


class TarjetaEliminadaOut(EliminadoOut):
    planes_msi_eliminados: int


# ------------------------------------------------------------------- deuda
class DeudaCrear(_Entrada):
    nombre: str = Field(min_length=1, max_length=100)
    acreedor: Optional[str] = Field(default=None, min_length=1, max_length=100)
    tipo: TipoDeuda
    monto_original: Dinero = Field(gt=0)
    saldo_actual: Dinero = Field(ge=0)
    tasa_anual: Optional[Tasa] = Field(default=None, ge=0, le=Decimal("999.99"))
    pago_mensual: Optional[Dinero] = Field(default=None, gt=0)
    dia_pago: Optional[Dia] = None
    fecha_inicio: Optional[date] = None


class DeudaEditar(_Edicion):
    NO_NULOS = ("nombre", "tipo", "monto_original", "saldo_actual")
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    acreedor: Optional[str] = Field(default=None, min_length=1, max_length=100)
    tipo: Optional[TipoDeuda] = None
    monto_original: Optional[Dinero] = Field(default=None, gt=0)
    saldo_actual: Optional[Dinero] = Field(default=None, ge=0)
    tasa_anual: Optional[Tasa] = Field(default=None, ge=0, le=Decimal("999.99"))
    pago_mensual: Optional[Dinero] = Field(default=None, gt=0)
    dia_pago: Optional[Dia] = None
    fecha_inicio: Optional[date] = None


class DeudaOut(BaseModel):
    id: int
    nombre: str
    acreedor: Optional[str]
    tipo: str
    monto_original: Dinero
    saldo_actual: Dinero
    tasa_anual: Optional[Tasa]
    pago_mensual: Optional[Dinero]
    dia_pago: Optional[int]
    fecha_inicio: Optional[date]
    estatus: str                              # derivado: saldo 0 => 'liquidada'
    proxima_fecha_pago: Optional[date]        # solo deudas activas con dia_pago


# --------------------------------------------------------------------- msi
class MsiCrear(_Entrada):
    tarjeta_id: int = Field(ge=1)
    categoria_id: Optional[int] = Field(default=None, ge=1)
    descripcion: str = Field(min_length=1, max_length=120)
    monto_original: Dinero = Field(gt=0)
    num_mensualidades: int = Field(ge=2, le=settings.max_mensualidades)
    mensualidades_pagadas: int = Field(default=0, ge=0)
    # Si no se manda, se calcula: monto_original / num_mensualidades (redondeo a centavos)
    monto_mensualidad: Optional[Dinero] = Field(default=None, gt=0)
    fecha_compra: date


class MsiEditar(_Edicion):
    NO_NULOS = ("tarjeta_id", "descripcion", "monto_original", "num_mensualidades",
                "mensualidades_pagadas", "monto_mensualidad", "fecha_compra", "estatus")
    tarjeta_id: Optional[int] = Field(default=None, ge=1)
    categoria_id: Optional[int] = Field(default=None, ge=1)
    descripcion: Optional[str] = Field(default=None, min_length=1, max_length=120)
    monto_original: Optional[Dinero] = Field(default=None, gt=0)
    num_mensualidades: Optional[int] = Field(default=None, ge=2, le=settings.max_mensualidades)
    mensualidades_pagadas: Optional[int] = Field(default=None, ge=0)
    monto_mensualidad: Optional[Dinero] = Field(default=None, gt=0)
    fecha_compra: Optional[date] = None
    # 'liquidado' no se puede mandar: lo pone el servidor cuando pagadas == total.
    estatus: Optional[Literal["activo", "cancelado"]] = None


class MsiOut(BaseModel):
    id: int
    tarjeta_id: int
    categoria_id: Optional[int]
    descripcion: str
    monto_original: Dinero
    num_mensualidades: int
    mensualidades_pagadas: int
    mensualidades_restantes: int          # derivado: total - pagadas
    monto_mensualidad: Dinero
    saldo_pendiente: Dinero               # derivado: restantes × mensualidad
    fecha_compra: date
    estatus: str
    origen: str
