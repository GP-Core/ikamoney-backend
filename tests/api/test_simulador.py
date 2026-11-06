"""Motor del simulador de compras (T41) con datos capturados por la API. "Hoy" es el 15 de marzo
de 2026. El endpoint es de T40: aquí se llama directo a simulador.simular(db, usuario, pedido)."""
import time

import pytest
from sqlalchemy import func, select

from app.models import PlanMsi, ScoreHistorial, Tarjeta, Usuario
from app.schemas.simulacion import SimulacionPedido
from app.services import simulador
from tests.conftest import TestSession


def ingreso(monto=20000):
    return {"tipo": "ingreso", "concepto": "Sueldo", "monto": monto, "frecuencia": "mensual",
            "fecha": "2026-01-01"}


def gasto(cat, monto, clase, fecha="2026-01-01"):
    return {"tipo": "gasto", "concepto": "Gasto", "monto": monto, "categoria_id": cat,
            "clase": clase, "fecha": fecha, "frecuencia": "mensual" if clase == "fijo" else "unico"}


def tarjeta(nombre, saldo, limite, tasa):
    return {"nombre": nombre, "banco": "Banco", "limite_credito": limite, "saldo_actual": saldo,
            "dia_corte": 10, "dia_pago": 30, "tasa_anual": tasa}


def post(client, h, ruta, cuerpo):
    r = client.post(f"/api/v1/{ruta}", json=cuerpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def simular(usuario_id, precio=9000, prioridad="media", ahorro=0, escenarios=None):
    pedido = SimulacionPedido(descripcion="Laptop", precio=precio, prioridad=prioridad,
                              ahorro_inicial=ahorro,
                              escenarios=escenarios or [{"tipo": "contado"}])
    with TestSession() as db:
        return simulador.simular(db, db.get(Usuario, usuario_id), pedido).model_dump(mode="json")


def msi(tarjeta_id, meses):
    return {"tipo": "msi", "tarjeta_id": tarjeta_id, "meses": meses}


def por_id(resultado):
    return {e["id"]: e for e in resultado["escenarios"]}


def contar(modelo) -> int:
    with TestSession() as db:
        return db.scalar(select(func.count()).select_from(modelo))


@pytest.fixture
def uid(usuario1):
    return usuario1[0]


@pytest.fixture
def perfil_t26(client, h, cat):
    """Perfil de ejemplo de T25 / T26 capturado por la API."""
    post(client, h, "movimientos", ingreso())
    post(client, h, "movimientos", gasto(cat, 8000, "fijo"))
    for fecha in ("2025-12-10", "2026-01-10", "2026-02-10"):
        post(client, h, "movimientos", gasto(cat, 4000, "variable", fecha))
    a = post(client, h, "tarjetas", tarjeta("Tarjeta A", 20000, 60000, 60))
    b = post(client, h, "tarjetas", tarjeta("Tarjeta B", 12000, 30000, 45))
    post(client, h, "msi", {"tarjeta_id": a["id"], "descripcion": "MSI 1", "monto_original": 12000,
                            "num_mensualidades": 12, "mensualidades_pagadas": 4,
                            "fecha_compra": "2025-11-10"})
    post(client, h, "msi", {"tarjeta_id": b["id"], "descripcion": "MSI 2", "monto_original": 6000,
                            "num_mensualidades": 6, "mensualidades_pagadas": 3,
                            "fecha_compra": "2025-12-10"})
    return a, b


# ------------------------------------------------------ CP-10 (T25 / T26)
def test_cp10_contado_descartado_y_12_msi_score_70(uid, perfil_t26):
    a, _ = perfil_t26
    d = simular(uid, ahorro=5000, escenarios=[{"tipo": "contado"}, msi(a["id"], 12)])
    assert d["estado"] == "calculado" and d["meses"] == 12
    assert d["score_actual"] == {"puntaje": 78, "nivel": "en_revision",
                                 "nivel_texto": "En revisión"}
    e = por_id(d)
    contado, doce = e["contado"], e[f"msi-{a['id']}-12"]

    assert contado["aplica"] and contado["mensualidad"] == 9000
    assert contado["balance"][0]["compra"] == 9000 and contado["balance"][1]["compra"] == 0
    assert contado["balance"][0]["acumulado"] == -162                # 5,000 + 3,838 − 9,000
    assert contado["indicadores"]["meses_en_negativo"] == 1
    assert (contado["veredicto"], contado["regla"]) == ("no_recomendable", "RN-15")
    assert "2026-03" in contado["razon"] and "-$162.00" in contado["razon"]

    assert doce["mensualidad"] == 750 and len(doce["balance"]) == 12
    assert doce["balance"][0] == {"mes": 1, "periodo": "2026-03", "ingresos": 20000.0,
                                  "gastos": 12000.0, "compromisos": 4912.0, "compra": 750.0,
                                  "flujo": 3088.0, "acumulado": 8088.0}
    assert doce["balance"][11]["compra"] == 750
    assert doce["indicadores"]["meses_en_negativo"] == 0
    assert doce["score"]["puntaje"] == 70 and doce["score"]["puntaje_bruto"] == 69.52   # CP-10
    assert doce["score"]["nivel"] == "en_revision" and doce["score"]["cambio"] == -8
    assert (doce["veredicto"], doce["regla"]) == ("recomendable", "RN-16")

    assert d["menor_impacto"] == doce["id"] and doce["menor_impacto"]
    assert not contado["menor_impacto"]
    assert (d["veredicto"], d["veredicto_texto"]) == ("recomendable", "Recomendable")


def test_estructura_de_respuesta(uid, perfil_t26):
    """Interfaz acordada con T40: si cambia, avisar a Daniel y a la pantalla del simulador."""
    a, _ = perfil_t26
    d = simular(uid, escenarios=[msi(a["id"], 6), msi(a["id"], 1)])
    assert set(d) == {"estado", "periodo", "descripcion", "precio", "prioridad", "meses",
                      "score_actual", "escenarios", "menor_impacto", "veredicto",
                      "veredicto_texto", "faltantes", "supuestos", "version_modelo"}
    campos = {"id", "tipo", "tarjeta_id", "tarjeta_nombre", "meses", "aplica", "motivo",
              "mensualidad", "balance", "indicadores", "score", "veredicto", "veredicto_texto",
              "regla", "razon", "menor_impacto"}
    assert all(set(e) == campos for e in d["escenarios"])
    assert set(d["escenarios"][0]["score"]) == {"puntaje", "puntaje_bruto", "nivel", "nivel_texto",
                                                "tope_aplicado", "motivo_tope", "cambio"}
    assert set(d["escenarios"][0]["indicadores"]) == {"flujo_minimo", "mes_flujo_minimo",
                                                      "acumulado_minimo", "meses_en_negativo",
                                                      "primer_mes_negativo"}


def test_rn16_prioridad_baja_solo_si_mantiene_el_nivel(uid, perfil_t26):
    a, _ = perfil_t26
    e = por_id(simular(uid, prioridad="baja", escenarios=[msi(a["id"], 12), msi(a["id"], 3)]))
    assert e[f"msi-{a['id']}-12"]["veredicto"] == "recomendable"       # 70: sigue En revisión
    tres = e[f"msi-{a['id']}-3"]
    assert tres["score"]["nivel"] == "en_riesgo" and tres["veredicto"] == "con_precaucion"


def test_rn16_prioridad_alta_aunque_el_indice_baje(uid, perfil_t26):
    a, _ = perfil_t26
    tres = simular(uid, prioridad="alta", escenarios=[msi(a["id"], 3)])["escenarios"][0]
    assert tres["score"]["nivel"] == "en_riesgo" and tres["veredicto"] == "recomendable"


def test_contado_con_ahorro_alcanza_pero_baja_el_indice(uid, perfil_t26):
    """Pagar con ahorro: el dinero alcanza todos los meses (RN-15 se cumple), pero el flujo del
    mes queda negativo y el índice baja a En riesgo, así que con prioridad media es con
    precaución (RN-16)."""
    c = simular(uid, ahorro=20000)["escenarios"][0]
    assert c["indicadores"]["meses_en_negativo"] == 0 and c["balance"][0]["flujo"] == -5162
    assert c["balance"][0]["acumulado"] == 14838                     # 20,000 + 3,838 − 9,000
    assert c["score"]["puntaje"] == 53 and c["score"]["nivel"] == "en_riesgo"
    assert c["veredicto"] == "con_precaucion"


# -------------------------------------------- escenarios que no aplican
def test_plazo_que_no_existe(uid, perfil_t26):
    a, _ = perfil_t26
    e = por_id(simular(uid, escenarios=[msi(a["id"], 1), msi(a["id"], 99), msi(a["id"], 6)]))
    for clave in (f"msi-{a['id']}-1", f"msi-{a['id']}-99"):
        assert not e[clave]["aplica"] and e[clave]["motivo"]["codigo"] == "PLAZO_NO_VALIDO"
        assert e[clave]["score"] is None and e[clave]["balance"] == []
        assert not e[clave]["menor_impacto"]
    assert e[f"msi-{a['id']}-6"]["aplica"]


def test_tarjeta_sin_limite_disponible(client, h, uid):
    post(client, h, "movimientos", ingreso())
    llena = post(client, h, "tarjetas", tarjeta("Llena", 30000, 30000, 50))
    poca = post(client, h, "tarjetas", tarjeta("Poca", 25000, 30000, 50))
    d = simular(uid, escenarios=[msi(llena["id"], 6), msi(poca["id"], 6)])
    e = por_id(d)
    assert e[f"msi-{llena['id']}-6"]["motivo"]["codigo"] == "LIMITE_INSUFICIENTE"
    assert "no tiene crédito disponible" in e[f"msi-{llena['id']}-6"]["motivo"]["mensaje"]
    assert "$5,000.00" in e[f"msi-{poca['id']}-6"]["motivo"]["mensaje"]
    assert d["estado"] == "sin_escenarios_validos" and d["menor_impacto"] is None
    assert d["veredicto"] is None


def test_el_limite_descuenta_los_msi_pendientes(uid, perfil_t26):
    """Tarjeta B: 30,000 − 12,000 de saldo − 3,000 del MSI 2 = 15,000 disponibles."""
    _, b = perfil_t26
    assert simular(uid, precio=15000, escenarios=[msi(b["id"], 6)])["escenarios"][0]["aplica"]
    e = simular(uid, precio="15000.01", escenarios=[msi(b["id"], 6)])["escenarios"][0]
    assert e["motivo"]["codigo"] == "LIMITE_INSUFICIENTE" and "$15,000.00" in e["motivo"]["mensaje"]


def test_tarjeta_inactiva_o_de_otro_usuario(client, h, h2, uid, perfil_t26):
    a, b = perfil_t26
    client.put(f"/api/v1/tarjetas/{b['id']}", json={"activa": False}, headers=h)
    ajena = post(client, h2, "tarjetas", tarjeta("Ajena", 0, 50000, 40))
    e = por_id(simular(uid, escenarios=[msi(b["id"], 6), msi(ajena["id"], 6), msi(a["id"], 6)]))
    for t in (b, ajena):
        assert e[f"msi-{t['id']}-6"]["motivo"]["codigo"] == "TARJETA_NO_DISPONIBLE"
    assert e[f"msi-{a['id']}-6"]["aplica"]


def test_escenario_repetido(uid, perfil_t26):
    a, _ = perfil_t26
    d = simular(uid, escenarios=[{"tipo": "contado"}, msi(a["id"], 6), {"tipo": "contado"},
                                 msi(a["id"], 6)])
    assert [e["aplica"] for e in d["escenarios"]] == [True, True, False, False]
    assert d["escenarios"][2]["motivo"]["codigo"] == "ESCENARIO_REPETIDO"


# ------------------------------------------------------------ casos borde
def test_sin_ingresos_no_simula(client, h, uid):
    t = post(client, h, "tarjetas", tarjeta("Tarjeta A", 0, 60000, 60))
    d = simular(uid, escenarios=[{"tipo": "contado"}, msi(t["id"], 6)])
    assert d["estado"] == "datos_faltantes" and d["escenarios"] == []
    assert d["faltantes"][0]["dato"] == "ingresos" and d["faltantes"][0]["obligatorio"]
    assert d["score_actual"] is None and d["veredicto"] is None


def test_msi_que_ya_comprometen_todo(client, h, uid, cat):
    """Las mensualidades ya se comen el ingreso: ninguna opción alcanza (RN-15), pero con
    prioridad alta se indica la de menor impacto."""
    post(client, h, "movimientos", ingreso(10000))
    post(client, h, "movimientos", gasto(cat, 1000, "fijo"))
    t = post(client, h, "tarjetas", tarjeta("Grande", 0, 200000, 0))
    post(client, h, "msi", {"tarjeta_id": t["id"], "descripcion": "Pantalla",
                            "monto_original": 120000, "num_mensualidades": 12,
                            "mensualidades_pagadas": 0, "fecha_compra": "2026-03-01"})
    d = simular(uid, precio=600, prioridad="alta",
                escenarios=[{"tipo": "contado"}, msi(t["id"], 12)])
    assert d["score_actual"]["puntaje"] <= 59                         # flujo negativo: tope
    assert all(e["veredicto"] == "no_recomendable" for e in d["escenarios"])
    assert d["menor_impacto"] in {e["id"] for e in d["escenarios"]}
    assert d["veredicto"] == "no_recomendable"
    assert d["veredicto_texto"] == "No se recomienda realizar esta compra por ahora"


def test_horizonte_cubre_el_plazo_mas_largo(uid, perfil_t26):
    a, _ = perfil_t26
    d = simular(uid, escenarios=[{"tipo": "contado"}, msi(a["id"], 18)])
    assert d["meses"] == 18 and all(len(e["balance"]) == 18 for e in d["escenarios"])
    dieciocho = d["escenarios"][1]
    assert dieciocho["balance"][17]["compra"] == 500 and dieciocho["mensualidad"] == 500


# --------------------------------------------------------- RN-17 y RNF
def test_simular_no_modifica_datos(uid, perfil_t26):
    a, _ = perfil_t26
    antes = (contar(Tarjeta), contar(PlanMsi), contar(ScoreHistorial))
    simular(uid, escenarios=[{"tipo": "contado"}, msi(a["id"], 12)])
    assert (contar(Tarjeta), contar(PlanMsi), contar(ScoreHistorial)) == antes


def test_responde_en_menos_de_2_segundos(uid, perfil_t26):
    a, b = perfil_t26
    escenarios = [{"tipo": "contado"}, msi(a["id"], 3), msi(a["id"], 6), msi(a["id"], 12),
                  msi(b["id"], 12), msi(a["id"], 24)]
    inicio = time.perf_counter()
    d = simular(uid, escenarios=escenarios)
    assert time.perf_counter() - inicio < 2
    assert len(d["escenarios"]) == 6 and all(e["aplica"] for e in d["escenarios"])