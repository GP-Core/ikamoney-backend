"""Reglas AL-01 a AL-04 (T47): función pura, sin base de datos."""
from datetime import date
from decimal import Decimal as D

import pytest

from app.services.alertas_reglas import (Configuracion, DatosAlertas, MesDatos, TarjetaDatos,
                                         evaluar, reglas_vigentes, utilizacion)

HOY = date(2026, 3, 15)
REGLAS = reglas_vigentes()
CONFIG = Configuracion(umbral_utilizacion=70, dias_anticipacion=3, canal_correo=True, canal_push=False)


def tarjeta(saldo=0, limite=10000, msi=0, pago=date(2026, 3, 30), id=1, nombre="BBVA Azul"):
    return TarjetaDatos(id=id, nombre=nombre, saldo=D(saldo), limite=D(limite),
                        pendiente_msi=D(msi), fecha_pago=pago)


def datos(tarjetas=(), meses=()):
    return DatosAlertas(hoy=HOY, meses=tuple(meses), tarjetas=tuple(tarjetas))


def reglas_de(d, config=CONFIG):
    return [h.regla for h in evaluar(d, config, REGLAS)]


def test_sin_datos_no_hay_alertas():
    assert reglas_de(datos()) == []


# ------------------------------------------------------------ AL-01
def test_al01_avisa_el_primer_mes_con_compromisos_mayores():
    meses = [MesDatos("2026-03", D(1000), D(900)), MesDatos("2026-04", D(1000), D(1001)),
             MesDatos("2026-05", D(1000), D(5000))]
    [h] = evaluar(datos(meses=meses), CONFIG, REGLAS)
    assert (h.regla, h.referencia, h.severidad) == ("AL-01", "proyeccion", "critica")
    assert "abril de 2026" in h.mensaje


def test_al01_compromisos_iguales_a_ingresos_no_alerta():
    assert reglas_de(datos(meses=[MesDatos("2026-03", D(1000), D(1000))])) == []


def test_al01_sin_ningun_ingreso_no_alerta():
    assert reglas_de(datos(meses=[MesDatos("2026-03", D(0), D(500))])) == []


# ------------------------------------------------------------ AL-02 y AL-04
@pytest.mark.parametrize("saldo,esperado", [(6999, []), (7000, ["AL-02"]), (10000, ["AL-02"]),
                                            (10001, ["AL-04"])])
def test_utilizacion_en_el_borde_del_umbral(saldo, esperado):
    assert reglas_de(datos([tarjeta(saldo)])) == esperado


def test_el_msi_pendiente_cuenta_en_la_utilizacion():
    assert reglas_de(datos([tarjeta(saldo=2000, msi=5000)])) == ["AL-02"]
    assert reglas_de(datos([tarjeta(saldo=2000, msi=9000)])) == ["AL-04"]


def test_el_umbral_es_configurable():
    config = Configuracion(50, 3, True, False)
    assert reglas_de(datos([tarjeta(5000)]), config) == ["AL-02"]
    assert reglas_de(datos([tarjeta(5000)])) == []


def test_sobre_el_limite_solo_avisa_al04_y_no_las_dos():
    assert reglas_de(datos([tarjeta(15000)])) == ["AL-04"]


def test_limite_cero_con_deuda_es_al04_y_sin_deuda_nada():
    assert reglas_de(datos([tarjeta(saldo=100, limite=0)])) == ["AL-04"]
    assert utilizacion(tarjeta(saldo=0, limite=0)) == 0
    assert reglas_de(datos([tarjeta(saldo=0, limite=0)])) == []


def test_cada_tarjeta_tiene_su_propia_alerta():
    hallazgos = evaluar(datos([tarjeta(8000, id=1), tarjeta(8000, id=2, nombre="Nu")]), CONFIG, REGLAS)
    assert [h.referencia for h in hallazgos] == ["tarjeta:1", "tarjeta:2"]
    assert len({h.clave for h in hallazgos}) == 2


# ------------------------------------------------------------ AL-03
@pytest.mark.parametrize("pago,esperado", [
    (date(2026, 3, 14), []),            # ya venció
    (date(2026, 3, 15), ["AL-03"]),     # hoy
    (date(2026, 3, 18), ["AL-03"]),     # justo en el límite de anticipación
    (date(2026, 3, 19), []),            # un día más lejos
])
def test_al03_dias_de_anticipacion(pago, esperado):
    assert reglas_de(datos([tarjeta(saldo=100, pago=pago)])) == esperado


def test_al03_sin_saldo_no_avisa():
    assert reglas_de(datos([tarjeta(saldo=0, pago=date(2026, 3, 16))])) == []


def test_al03_lleva_la_fecha_en_la_referencia_y_se_configura():
    [h] = evaluar(datos([tarjeta(100, pago=date(2026, 3, 18))]), CONFIG, REGLAS)
    assert h.referencia == "tarjeta:1:2026-03-18" and "18 de marzo" in h.mensaje
    assert reglas_de(datos([tarjeta(100, pago=date(2026, 3, 18))]),
                     Configuracion(70, 2, True, False)) == []


# ------------------------------------------------------------ IC-07
def test_los_textos_no_llevan_saldos_ni_limites():
    d = datos([tarjeta(saldo=31337, limite=40000, msi=1234, pago=date(2026, 3, 16))],
              [MesDatos("2026-04", D(777), D(98765))])
    textos = " ".join(f"{h.titulo} {h.mensaje} {h.accion}" for h in evaluar(d, CONFIG, REGLAS))
    for numero in ("31337", "31,337", "40000", "40,000", "1234", "98765", "98,765", "777"):
        assert numero not in textos
