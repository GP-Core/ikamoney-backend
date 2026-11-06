"""Capa de API del simulador de compras (T40): valida lo que el motor no valida, arma los
escenarios y traduce el resultado a las respuestas de T17. El cálculo es del motor de T41
(app/services/simulador.py); aquí no hay fórmulas ni se guarda nada (RN-17, REQ-SC-07)."""
from sqlalchemy.orm import Session

from app.core.errores import ApiError, campo_error
from app.models import Usuario
from app.schemas.simulacion import (EscenarioPedido, SimulacionOut, SimulacionPedido,
                                    SimulacionPeticion)
from app.services import simulador, tarjetas

# Plazos a MSI que se evalúan cuando el usuario no elige escenarios: los de CP-10 de T25.
# Propuesta pendiente de confirmar con el equipo; cambiarla aquí no afecta a nada más.
PLAZOS_POR_OMISION = (3, 6, 12, 18)


def escenarios_por_omision(db: Session, usuario: Usuario) -> list[EscenarioPedido]:
    """Contado, y a MSI en los plazos por omisión con la tarjeta activa de mayor crédito
    disponible. Sin tarjetas activas solo se evalúa de contado. Si la tarjeta elegida no
    alcanza para algún plazo, el motor lo devuelve con aplica = false y su motivo."""
    lista = [EscenarioPedido(tipo="contado")]
    activas = tarjetas.listar(db, usuario, activa=True)
    if activas:
        mejor = max(activas, key=lambda t: (t.credito_disponible, -t.id))
        lista += [EscenarioPedido(tipo="msi", tarjeta_id=mejor.id, meses=m)
                  for m in PLAZOS_POR_OMISION]
    return lista


def verificar_tarjetas(db: Session, usuario: Usuario, escenarios: list[EscenarioPedido]) -> None:
    """Una tarjeta que no existe o es de otro usuario es un error (404), igual que en los demás
    endpoints. Una tarjeta del usuario que no se puede usar (inactiva, sin crédito) no lo es:
    el motor la devuelve con aplica = false."""
    for i, e in enumerate(escenarios):
        if e.tipo != "msi":
            continue
        try:
            tarjetas.obtener(db, usuario, e.tarjeta_id)
        except ApiError as error:
            raise ApiError(error.status, error.codigo, error.mensaje,
                           [campo_error(f"escenarios.{i}.tarjeta_id", error.mensaje)]) from None


def calcular(db: Session, usuario: Usuario, peticion: SimulacionPeticion) -> SimulacionOut:
    escenarios = peticion.escenarios or escenarios_por_omision(db, usuario)
    verificar_tarjetas(db, usuario, escenarios)

    pedido = SimulacionPedido(**peticion.model_dump(exclude={"escenarios"}),
                              escenarios=escenarios)
    resultado = simulador.simular(db, usuario, pedido)

    if resultado.estado == "datos_faltantes":       # sin ingresos no se simula (REQ-SC-10)
        raise ApiError(400, "SIN_INGRESOS", "Registra tus ingresos para poder simular una compra.",
                       [campo_error(f.dato, f.mensaje) for f in resultado.faltantes
                        if f.obligatorio])
    return resultado
