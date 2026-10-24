"""Anonimización y detección de estados de cuenta (sin HTTP ni IA)."""
import pytest

from app.services.estados_cuenta import deteccion
from app.services.estados_cuenta.privacidad import (DatosSensiblesError, limpiar_texto,
                                                     terminos_del_nombre, verificar)


@pytest.mark.parametrize("texto", ["Tarjeta 5204 1234 5678 9012", "Tarjeta 5204-1234-5678-9012",
                                   "CLABE 012180001234567891", "RFC GODE561231GR8",
                                   "CURP GODE561231HDFRRN09"])
def test_detecta_tarjeta_clabe_rfc_y_curp(texto):
    with pytest.raises(DatosSensiblesError):
        verificar(texto)


def test_acepta_terminaciones_enmascaradas_montos_y_fechas():
    verificar("Tarjeta **** **** **** 1234\nSaldo $12,345.67 pago 1,234.56 corte 15/08/2026")


def test_el_error_no_muestra_el_dato():
    with pytest.raises(DatosSensiblesError) as error:
        verificar("5204 1234 5678 9012")
    assert "5204" not in str(error.value) and "9012" not in str(error.value)


def test_nombre_sin_acentos_y_partido_en_dos_lineas():
    terminos = terminos_del_nombre("Ana Lucía Pérez Muñoz")
    texto = "ANA LUCIA\nPEREZ MUNOZ\nTarjeta 5204 1234 5678 9012\nCLABE 012180001234567891"
    limpio = limpiar_texto(texto, terminos)
    verificar(limpio, terminos)
    assert "ANA" not in limpio and "5204" not in limpio
    assert "[DATO_PERSONAL]" in limpio


def test_borra_cada_palabra_del_nombre_aunque_falte_alguna():
    terminos = terminos_del_nombre("Ana Lucía Pérez Muñoz")
    limpio = limpiar_texto("Titular: PEREZ MUNOZ ANA", terminos)   # orden y palabras distintos
    assert "PEREZ" not in limpio and "MUNOZ" not in limpio and "ANA" not in limpio


def test_no_busca_particulas_del_nombre():
    assert terminos_del_nombre("María de la Luz") == ["María de la Luz", "María", "Luz"]
    assert "PAGO DEL PERIODO" in limpiar_texto("PAGO DEL PERIODO", terminos_del_nombre("Luis Del Río"))


def test_parece_estado_de_cuenta():
    assert deteccion.parece_estado_de_cuenta("ESTADO DE CUENTA\nFecha límite de pago: 20/09/2026")
    assert deteccion.parece_estado_de_cuenta("FECHADECORTE 31/08 PAGOMINIMO 300")   # palabras pegadas
    assert not deteccion.parece_estado_de_cuenta("Factura de luz. Fecha de corte del servicio.")
