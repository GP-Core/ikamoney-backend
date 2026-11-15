"""Endpoint del simulador de compras (T40). Solo HTTP: valida, delega en app/services/simulaciones.py
y no guarda nada. Guardar una simulación es otro endpoint."""
from fastapi import APIRouter

from app.api.deps import Db, UsuarioActual
from app.schemas.simulacion import SimulacionOut, SimulacionPeticion
from app.services import simulaciones as servicio

router = APIRouter(prefix="/simulador", tags=["Simulador"])


@router.post("/calcular", response_model=SimulacionOut,
             summary="Impacto de comprar algo de contado o a MSI en cada escenario (T25, Fórmula 4)",
             responses={
                 400: {"description": "SIN_INGRESOS: sin ingresos registrados no se puede simular"},
                 404: {"description": "TARJETA_NO_ENCONTRADA: la tarjeta no existe o es de otro usuario"},
             })
def calcular(peticion: SimulacionPeticion, db: Db, usuario: UsuarioActual):
    return servicio.calcular(db, usuario, peticion)
