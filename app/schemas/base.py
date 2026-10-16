"""Piezas comunes de todos los esquemas: tipos monetarios, clases base y respuesta de borrado."""
from decimal import Decimal
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

_a_float = PlainSerializer(lambda v: float(v), return_type=float, when_used="json")
Dinero = Annotated[Decimal, Field(max_digits=12, decimal_places=2), _a_float]
Tasa = Annotated[Decimal, Field(max_digits=5, decimal_places=2), _a_float]
Dia = Annotated[int, Field(ge=1, le=31)]


class Entrada(BaseModel):
    # extra="forbid": un campo que no existe (p. ej. usuario_id o un número de tarjeta
    # completo) se rechaza con 422 en vez de ignorarse en silencio.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Edicion(Entrada):
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
