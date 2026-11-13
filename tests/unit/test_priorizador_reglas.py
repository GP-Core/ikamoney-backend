"""Priorizador de deudas (T43): Fórmula 9 de T25, razones en dinero y reglas RN-18 a RN-20,
sin base de datos ni HTTP."""
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.services import priorizador as p
from app.services.priorizador import Candidata

D = Decimal


def r2(valor) -> Decimal:
    return D(valor).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def tarjeta(id_, nombre, saldo, limite, tasa, pendiente=0):
    return Candidata(tipo="tarjeta", id=id_, nombre=nombre, saldo=D(saldo),
                     tasa_anual=None if tasa is None else D(tasa) / 100,
                     limite=D(limite), pendiente_msi=D(pendiente))


def deuda(id_, nombre, saldo, tasa, pago=None):
    return Candidata(tipo="deuda", id=id_, nombre=nombre, saldo=D(saldo),
                     tasa_anual=None if tasa is None else D(tasa) / 100,
                     pago_mensual=None if pago is None else D(pago))


A = tarjeta(1, "Tarjeta A", 20000, 60000, 60, pendiente=8000)
B = tarjeta(2, "Tarjeta B", 12000, 30000, 45, pendiente=3000)


def ranking(*candidatas):
    entran, fuera = p.separar(list(candidatas))
    return p.ordenar(entran), fuera


# ------------------------------------------------- CP-11 (T25 / T26)
def test_cp11_costo_de_cada_tarjeta():
    a, b = p.costo(A), p.costo(B)
    assert r2(a.tasa_mensual * 100) == D("5.80") and r2(b.tasa_mensual * 100) == D("4.35")
    assert a.interes_mes == D(1160) and b.interes_mes == D(522)                 # Fórmula 5
    assert a.pago_minimo == D(1460) and b.pago_minimo == D(702)                 # Fórmula 6
    assert r2(a.utilizacion * 100) == D("46.67") and b.utilizacion == D("0.5")  # con MSI pendiente
    assert round(a.costo_anual_compuesto * 100, 1) == D("96.7")
    assert round(b.costo_anual_compuesto * 100, 1) == D("66.7")
    assert a.ahorro_por_mil == D(58) and b.ahorro_por_mil == D("43.5")


def test_cp11_orden_a_luego_b():
    orden, _ = ranking(B, A)
    assert [k.candidata.nombre for k in orden] == ["Tarjeta A", "Tarjeta B"]


def test_cp11_razones_en_dinero():
    orden, _ = ranking(A, B)
    pos = p.posiciones(orden)
    assert "más cara" in pos[0].razon and "$1,160.00" in pos[0].razon and "$58.00" in pos[0].razon
    assert "tasa es menor" in pos[1].razon and "$14.50" in pos[1].razon
    assert "mínimo ($702.00) hasta liquidar Tarjeta A" in pos[1].razon
    assert pos[1].comparacion.criterio == "tasa" and pos[1].comparacion.ahorro_por_mil_menos == 14.5
    assert [x.accion for x in pos] == ["abonar_extra", "pagar_minimo"]          # RN-20


# ------------------------------------------- Fórmula 9: desempates (CE-08)
def test_ce08_misma_tasa_gana_la_mas_usada():
    poco = tarjeta(1, "Poco uso", 5000, 50000, 50)            # 10 %
    mucho = tarjeta(2, "Mucho uso", 8000, 10000, 50)          # 80 %
    orden, _ = ranking(poco, mucho)
    assert [k.candidata.nombre for k in orden] == ["Mucho uso", "Poco uso"]
    assert p.posiciones(orden)[1].comparacion.criterio == "utilizacion"


def test_ce08_misma_tasa_y_uso_gana_la_de_menor_saldo():
    grande = tarjeta(1, "Grande", 10000, 20000, 50)           # 50 %
    chica = tarjeta(2, "Chica", 5000, 10000, 50)              # 50 %
    orden, _ = ranking(grande, chica)
    assert [k.candidata.nombre for k in orden] == ["Chica", "Grande"]
    pos = p.posiciones(orden)
    assert pos[1].comparacion.criterio == "saldo" and "se liquida antes" in pos[1].razon


def test_rn18_no_ordena_por_lo_que_se_debe():
    """La deuda más grande con tasa baja va después de una chica con tasa alta."""
    hipoteca = deuda(1, "Hipoteca", 900000, 11, pago=9000)
    tienda = tarjeta(2, "Tienda", 3000, 5000, 90)
    orden, _ = ranking(hipoteca, tienda)
    assert [k.candidata.nombre for k in orden] == ["Tienda", "Hipoteca"]


def test_deudas_usan_tasa_entre_12_como_la_proyeccion():
    auto = p.costo(deuda(1, "Auto", 120000, 12, pago=4500))
    assert auto.tasa_mensual == D("0.01") and auto.interes_mes == D(1200)
    assert auto.pago_minimo == D(4500) and auto.utilizacion is None


# --------------------------------------------------- RN-19 y exclusiones
@pytest.mark.parametrize("candidata,motivo", [
    (tarjeta(1, "Sin saldo", 0, 30000, 50), "SIN_SALDO"),
    (tarjeta(1, "Sin tasa", 5000, 30000, None), "SIN_TASA"),
    (deuda(1, "Familiar", 10000, 0, pago=1000), "SIN_INTERESES"),
    (deuda(1, "Liquidada", 0, 20), "SIN_SALDO"),
])
def test_no_entran_al_ranking(candidata, motivo):
    orden, fuera = ranking(candidata)
    assert orden == [] and fuera[0].motivo == motivo and fuera[0].mensaje


# ------------------------------------------------------------ casos borde
def test_una_sola_deuda():
    orden, _ = ranking(A)
    pos = p.posiciones(orden)
    assert len(pos) == 1 and pos[0].posicion == 1 and "única deuda" in pos[0].razon
    assert p.bola_de_nieve(orden) is None


def test_sin_deudas():
    orden, fuera = ranking()
    assert orden == [] and fuera == [] and p.posiciones(orden) == []
    assert p.resumen(orden, D(0), D(0)) == "No tienes deudas que te cobren intereses."
    assert "MSI" in p.resumen(orden, D(0), D(1500))


def test_tarjeta_con_limite_en_cero():
    sin_limite = tarjeta(1, "Sin límite", 4000, 0, 50)
    k = p.costo(sin_limite)
    assert k.utilizacion is None and k.interes_mes > 0          # no divide entre cero
    pos = p.posiciones(p.ordenar([k]))
    assert [a.codigo for a in pos[0].avisos] == ["LIMITE_CERO"] and pos[0].utilizacion is None


def test_tarjeta_sobre_el_limite_avisa():
    k = p.costo(tarjeta(1, "Pasada", 12000, 10000, 50))
    assert [a.codigo for a in p.avisos(k)] == ["SOBRE_LIMITE"]


@pytest.mark.parametrize("pago,codigo", [(None, "SIN_PAGO_MENSUAL"),
                                         (100, "PAGO_NO_CUBRE_INTERES")])
def test_avisos_de_deudas(pago, codigo):
    k = p.costo(deuda(1, "Préstamo", 50000, 36, pago=pago))      # interés 1,500 al mes
    assert [a.codigo for a in p.avisos(k)] == [codigo]


# --------------------------------------------- consejo popular (bola de nieve)
def test_bola_de_nieve_difiere_y_dice_cuanto_cuesta():
    bn = p.bola_de_nieve(ranking(A, B)[0])
    assert not bn.coincide and bn.mas_chica == "tarjeta-2" and bn.diferencia_por_mil == D("14.50")
    assert "$14.50 más de intereses" in bn.mensaje


def test_bola_de_nieve_coincide():
    chica_cara = tarjeta(1, "Chica cara", 2000, 10000, 80)
    grande_barata = tarjeta(2, "Grande barata", 30000, 60000, 30)
    bn = p.bola_de_nieve(ranking(chica_cara, grande_barata)[0])
    assert bn.coincide and bn.diferencia_por_mil == 0


def test_resumen_rn20_cubre_minimos_y_dice_a_cual_abonar():
    orden, _ = ranking(A, B)
    texto = p.resumen(orden, D(2162), D(2000))
    assert "mínimo de todas" in texto and "$2,162.00" in texto and "$2,000.00" in texto
    assert texto.endswith("abónalo a Tarjeta A.")