"""T53b: la app sigue funcionando completa con los campos cifrados, y la migración conserva los datos."""
from decimal import Decimal

import pytest
from sqlalchemy import text

from app import migrar_cifrado
from app.core import cifrado
from app.core.cifrado import COLUMNAS_CIFRADAS, PREFIJO
from tests.conftest import DEUDA, TARJETA, TestSession, test_engine


def _crudo(tabla, columna):
    with TestSession() as db:
        return [r[0] for r in db.execute(text(f"SELECT {columna} FROM {tabla} ORDER BY id"))]


def _llenar(client, h, cat):
    t = client.post("/api/v1/tarjetas", json=TARJETA, headers=h).json()
    client.post("/api/v1/msi", headers=h, json={"tarjeta_id": t["id"], "descripcion": "Laptop",
                                                "monto_original": 12000, "num_mensualidades": 12,
                                                "fecha_compra": "2026-01-10"})
    client.post("/api/v1/deudas", json=DEUDA, headers=h)
    client.post("/api/v1/deudas", json={**DEUDA, "nombre": "Sin pago", "pago_mensual": None}, headers=h)
    client.post("/api/v1/movimientos", headers=h, json={
        "tipo": "ingreso", "concepto": "Sueldo", "monto": 20000, "frecuencia": "mensual",
        "fecha": "2026-03-01"})
    return t


def _respuestas(client, h):
    return {ruta: client.get(f"/api/v1/{ruta}", headers=h).json()
            for ruta in ("tarjetas", "msi", "deudas", "score", "proyeccion?meses=12", "priorizador")}


# ------------------------------------------------------------ la app completa sobre datos cifrados
def test_los_datos_se_guardan_cifrados_y_la_api_responde_igual(client, h, cat):
    _llenar(client, h, cat)
    assert all(v.startswith(PREFIJO) for v in _crudo("tarjeta", "limite_credito") + _crudo("tarjeta", "saldo_actual"))
    assert all(v.startswith(PREFIJO) for v in _crudo("plan_msi", "monto_mensualidad"))
    assert _crudo("deuda", "pago_mensual")[1] is None                       # NULL sigue siendo NULL
    assert _crudo("ingreso", "monto") == [20000] or Decimal(str(_crudo("ingreso", "monto")[0])) == 20000
    t = client.get("/api/v1/tarjetas", headers=h).json()[0]
    assert (t["limite_credito"], t["saldo_actual"], t["credito_disponible"]) == (20000, 5000, 15000)
    assert client.get("/api/v1/score", headers=h).json()["estado"] == "calculado"


def test_la_misma_base_cifrada_o_en_claro_da_las_mismas_respuestas(client, h, cat):
    """Prueba de la migración de punta a punta: cifrado → claro → cifrado no cambia ninguna respuesta."""
    _llenar(client, h, cat)
    cifradas = _respuestas(client, h)
    migrar_cifrado.ejecutar(test_engine, revertir=True, ddl=False)
    assert all(not str(v).startswith(PREFIJO) for v in _crudo("tarjeta", "saldo_actual"))
    assert _respuestas(client, h) == cifradas
    migrar_cifrado.ejecutar(test_engine, ddl=False)
    assert _respuestas(client, h) == cifradas


def test_filtrar_o_ordenar_por_saldo_ya_no_se_hace_en_sql(client, h, cat):
    """Documenta la limitación: ordenar por la columna cifrada daría un orden sin sentido."""
    client.post("/api/v1/tarjetas", json={**TARJETA, "nombre": "A", "saldo_actual": 100}, headers=h)
    client.post("/api/v1/tarjetas", json={**TARJETA, "nombre": "B", "saldo_actual": 99999}, headers=h)
    prior = client.get("/api/v1/priorizador", headers=h).json()
    assert prior is not None   # el priorizador ordena en Python y sigue respondiendo


# ------------------------------------------------------------ migración (parte de datos)
def _a_claro_heredado(conn=None):
    """Deja la base como estaría tras el ALTER: texto en claro sin prefijo, que es lo que migra el script."""
    migrar_cifrado.ejecutar(test_engine, revertir=True, ddl=False)


def test_la_migracion_cifra_los_datos_heredados_y_conserva_las_sumas(client, h, cat, capsys):
    _llenar(client, h, cat)
    _a_claro_heredado()
    with test_engine.connect() as c:
        antes = migrar_cifrado.foto(c)
    assert _crudo("tarjeta", "limite_credito") == ["20000.00"]
    migrar_cifrado.ejecutar(test_engine, ddl=False)
    with test_engine.connect() as c:
        assert migrar_cifrado.foto(c) == antes
    assert all(v.startswith(PREFIJO) for v in _crudo("tarjeta", "limite_credito"))
    assert antes["tarjeta.limite_credito"] == (1, 1, Decimal("20000.00"))
    assert antes["deuda.pago_mensual"] == (2, 1, Decimal("4500.00"))      # un NULL: no cuenta en la suma


def test_la_migracion_se_puede_repetir_sin_efecto(client, h, cat):
    _llenar(client, h, cat)
    migrar_cifrado.ejecutar(test_engine, ddl=False)
    primero = _crudo("tarjeta", "saldo_actual")
    migrar_cifrado.ejecutar(test_engine, ddl=False)
    assert _crudo("tarjeta", "saldo_actual") == primero            # ni siquiera se vuelve a cifrar
    with test_engine.begin() as c:
        assert migrar_cifrado.transformar_filas(c, cifrar=True) == 0


def test_la_simulacion_no_escribe(client, h, cat):
    _llenar(client, h, cat)
    _a_claro_heredado()
    migrar_cifrado.ejecutar(test_engine, simular=True, ddl=False)
    assert _crudo("tarjeta", "saldo_actual") == ["5000.00"]


def test_si_las_sumas_no_cuadran_no_se_confirma_nada(client, h, cat, monkeypatch):
    _llenar(client, h, cat)
    _a_claro_heredado()
    original = migrar_cifrado.transformar_filas

    def corrompe(conn, cifrar):
        n = original(conn, cifrar)
        conn.execute(text("UPDATE tarjeta SET saldo_actual = :v"),
                     {"v": cifrado.cifrar_texto("1.00", "tarjeta.saldo_actual")})
        return n

    monkeypatch.setattr(migrar_cifrado, "transformar_filas", corrompe)
    with pytest.raises(migrar_cifrado.MigracionError, match="no coinciden"):
        migrar_cifrado.ejecutar(test_engine, ddl=False)
    assert _crudo("tarjeta", "saldo_actual") == ["5000.00"]        # la transacción se revirtió


def test_con_otra_llave_la_migracion_no_arranca_a_ciegas(client, h, cat, monkeypatch):
    _llenar(client, h, cat)
    from app.core.config import settings
    import base64
    monkeypatch.setattr(settings, "cifrado_llave", base64.urlsafe_b64encode(b"o" * 32).decode())
    with pytest.raises(cifrado.ErrorCifrado):
        migrar_cifrado.ejecutar(test_engine, ddl=False)


def test_sin_confirmar_el_respaldo_no_escribe(capsys):
    assert migrar_cifrado.main([]) == 2
    assert "--confirmo-respaldo" in capsys.readouterr().err


def test_la_migracion_cubre_todas_las_columnas_cifradas():
    cubiertas = {(t, c) for t, cols in migrar_cifrado._tablas().items() for c, _, _ in cols}
    assert cubiertas == {(t, c) for t, c, _, _ in COLUMNAS_CIFRADAS}
    assert set(migrar_cifrado.CHECKS_AL_REVERTIR) <= set(migrar_cifrado._tablas())
