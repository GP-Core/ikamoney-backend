"""Cifrado de campos sensibles (T53b): AES-256-GCM, formato, contexto y el tipo de columna."""
import base64
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core import cifrado
from app.core.cifrado import (COLUMNAS_CIFRADAS, PREFIJO, DineroCifrado, ErrorCifrado, a_decimal,
                              a_texto, cifrar_texto, descifrar_texto)
from app.core.config import settings
from app.core.database import Base
from app.models import Tarjeta
from tests.conftest import TestSession


def _llave(byte: bytes = b"k") -> str:
    return base64.urlsafe_b64encode(byte * 32).decode()


# ------------------------------------------------------------ mecánica
def test_ida_y_vuelta_con_prefijo_de_version():
    c = cifrar_texto("12345.67", "tarjeta.saldo_actual")
    assert c.startswith(PREFIJO) and "12345" not in c
    assert descifrar_texto(c, "tarjeta.saldo_actual") == "12345.67"


def test_el_mismo_valor_da_un_resultado_distinto_cada_vez():
    assert len({cifrar_texto("100.00", "x.y") for _ in range(20)}) == 20


def test_el_contexto_impide_copiar_un_valor_a_otra_columna():
    c = cifrar_texto("100.00", "tarjeta.limite_credito")
    with pytest.raises(ErrorCifrado, match="tarjeta.saldo_actual"):
        descifrar_texto(c, "tarjeta.saldo_actual")


def test_con_otra_llave_no_descifra(monkeypatch):
    c = cifrar_texto("100.00", "x.y")
    monkeypatch.setattr(settings, "cifrado_llave", _llave(b"z"))
    with pytest.raises(ErrorCifrado):
        descifrar_texto(c, "x.y")


def test_un_valor_alterado_se_detecta():
    c = cifrar_texto("100.00", "x.y")
    crudo = bytearray(base64.b64decode(c[3:]))
    crudo[-1] ^= 1
    with pytest.raises(ErrorCifrado):
        descifrar_texto(PREFIJO + base64.b64encode(bytes(crudo)).decode(), "x.y")
    with pytest.raises(ErrorCifrado):
        descifrar_texto(PREFIJO + "no es base64!!", "x.y")


def test_el_error_no_revela_el_valor():
    with pytest.raises(ErrorCifrado) as e:
        descifrar_texto(PREFIJO + "AAAA", "tarjeta.saldo_actual")
    assert "AAAA" not in str(e.value)


# ------------------------------------------------------------ la llave
@pytest.mark.parametrize("llave,mensaje", [("", "Falta CIFRADO_LLAVE"), ("corta", "base64"),
                                           ("!!!no-base64", "base64"), (_llave(b"k" * 1)[:-4], "32 bytes")])
def test_sin_llave_valida_no_se_cifra_ni_arranca(monkeypatch, llave, mensaje):
    monkeypatch.setattr(settings, "cifrado_llave", llave)
    with pytest.raises(ErrorCifrado, match=mensaje):
        cifrado.verificar_llave()
    with pytest.raises(ErrorCifrado):
        cifrar_texto("1.00", "x.y")


def test_acepta_la_llave_en_base64_normal_o_url(monkeypatch):
    crudo = bytes(range(250, 218, -1))                      # produce + y / en base64 normal
    for codigo in (base64.b64encode(crudo).decode(), base64.urlsafe_b64encode(crudo).decode()):
        monkeypatch.setattr(settings, "cifrado_llave", codigo)
        cifrado.verificar_llave()
        assert descifrar_texto(cifrar_texto("5.00", "x.y"), "x.y") == "5.00"


# ------------------------------------------------------------ valores
@pytest.mark.parametrize("entrada,esperado", [(Decimal("1234.5"), "1234.50"), (10, "10.00"),
                                              ("0.005", "0.01"), (0.1, "0.10"),
                                              (Decimal("9999999999.99"), "9999999999.99")])
def test_a_texto_normaliza_a_centavos(entrada, esperado):
    assert a_texto(entrada, "x.y") == esperado


@pytest.mark.parametrize("malo", [Decimal("NaN"), Decimal("Infinity"), "abc", Decimal("1e12"),
                                  Decimal("10000000000")])
def test_a_texto_rechaza_lo_que_la_base_no_aceptaria(malo):
    with pytest.raises(ValueError):
        a_texto(malo, "x.y")


def test_a_decimal_lee_cifrado_en_claro_y_decimal():
    assert a_decimal(cifrar_texto("7.50", "x.y"), "x.y") == Decimal("7.50")
    assert a_decimal("7.5", "x.y") == Decimal("7.50")          # sin prefijo: dato heredado
    assert a_decimal(Decimal("7.5"), "x.y") == Decimal("7.50")  # columna que aún era DECIMAL


# ------------------------------------------------------------ el tipo de columna y los modelos
def _columnas_cifradas_en_modelos():
    return {(t.name, c.name, c.nullable) for t in Base.metadata.tables.values()
            for c in t.columns if isinstance(c.type, DineroCifrado)}


def test_la_lista_de_columnas_coincide_con_los_modelos():
    assert _columnas_cifradas_en_modelos() == {(t, c, n) for t, c, n, _ in COLUMNAS_CIFRADAS}


def test_el_contexto_de_cada_columna_es_su_tabla_y_nombre():
    for tabla in Base.metadata.tables.values():
        for c in tabla.columns:
            if isinstance(c.type, DineroCifrado):
                assert c.type.contexto == f"{tabla.name}.{c.name}"


def test_ingresos_y_gastos_quedan_sin_cifrar():
    for nombre in ("ingreso", "gasto"):
        assert not isinstance(Base.metadata.tables[nombre].c.monto.type, DineroCifrado)


def test_en_la_base_se_guarda_cifrado_y_el_modelo_devuelve_decimal(usuario1):
    with TestSession() as db:
        t = Tarjeta(usuario_id=usuario1[0], nombre="Prueba", banco="B", limite_credito=Decimal("31337.50"),
                    saldo_actual=Decimal("4242.42"), dia_corte=1, dia_pago=20)
        db.add(t)
        db.commit()
        tid = t.id
    with TestSession() as db:
        crudo = db.execute(text("SELECT limite_credito, saldo_actual FROM tarjeta WHERE id = :i"),
                           {"i": tid}).one()
        assert all(v.startswith(PREFIJO) for v in crudo)
        assert "31337" not in crudo[0] and "4242" not in crudo[1]
        leida = db.get(Tarjeta, tid)
        assert (leida.limite_credito, leida.saldo_actual) == (Decimal("31337.50"), Decimal("4242.42"))
        assert isinstance(leida.saldo_actual, Decimal)


def test_none_se_guarda_como_nulo(usuario1):
    from app.models import Deuda
    with TestSession() as db:
        d = Deuda(usuario_id=usuario1[0], nombre="x", tipo="otro", monto_original=Decimal("10"),
                  saldo_actual=Decimal("10"), pago_mensual=None)
        db.add(d)
        db.commit()
        assert db.execute(text("SELECT pago_mensual FROM deuda")).scalar() is None
        assert db.get(Deuda, d.id).pago_mensual is None
