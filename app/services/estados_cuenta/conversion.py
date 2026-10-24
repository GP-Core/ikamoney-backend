"""De la respuesta de la IA (esquema_ia.py) a la respuesta de la API (T17 §4)."""
from decimal import Decimal
from typing import Optional

from app.schemas.estado_cuenta import (EstadoCuentaExtraidoOut, MovimientoExtraidoOut,
                                       MsiExtraidoOut, TarjetaExtraidaOut)
from app.services.estados_cuenta.esquema_ia import EstadoCuentaIA
from app.services.fechas import a_centavos

A_MESES = ("msi", "meses_con_intereses")
NO_SON_CARGOS = ("pago", "devolucion")


def quitar_compras_a_meses_repetidas(datos: dict) -> int:
    """Quita la compra original completa cuando también está su mensualidad (PoC T08).

    Algunos bancos (por ejemplo BBVA) muestran la compra completa y, aparte, la mensualidad del
    periodo. Si una compra a meses trae como monto su precio completo y ya existe una mensualidad
    del mismo plan (monto original y plazo), la compra completa sobra. Devuelve cuántas quitó.
    """
    def plan(m):
        meses = m.get("meses") or {}
        return meses.get("monto_original"), meses.get("meses_totales")

    def es_compra_completa(m):
        original, plazo = plan(m)
        return m.get("modalidad") in A_MESES and original and (plazo or 0) > 1 and abs(m["monto"] - original) < 0.01

    movimientos = datos["movimientos"]
    con_mensualidad = {plan(m) for m in movimientos if m.get("modalidad") in A_MESES and not es_compra_completa(m)}
    datos["movimientos"] = [m for m in movimientos if not (es_compra_completa(m) and plan(m) in con_mensualidad)]
    return len(movimientos) - len(datos["movimientos"])


def _monto(valor: Optional[float]) -> Optional[Decimal]:
    return None if valor is None else a_centavos(Decimal(str(valor)))


def _dia(fecha: Optional[str]) -> Optional[int]:
    return None if fecha is None else int(fecha[-2:])   # AAAA-MM-DD


def a_contrato(estado: EstadoCuentaIA) -> EstadoCuentaExtraidoOut:
    """Arma la respuesta de /extraer.

    - `msi`: solo meses sin intereses; `mensualidadesPagadas` es la mensualidad que se cobra en
      este periodo ("2 de 6" => 2).
    - `movimientos`: solo cargos. Las mensualidades MSI ya van en `msi` y los pagos y abonos no
      son gastos; los meses con intereses sí se quedan aquí.
    """
    datos = estado.model_dump(mode="json")
    quitar_compras_a_meses_repetidas(datos)

    tarjeta = TarjetaExtraidaOut(
        banco=datos["banco"],
        limite_credito=_monto(datos["credito"]["limite_credito"]),
        saldo_actual=_monto(datos["pagos"]["total_a_pagar_periodo"]),
        tasa_anual=_monto(datos["tasas"]["tasa_interes_anual"]),
        pago_minimo=_monto(datos["pagos"]["pago_minimo"]),
        pago_no_intereses=_monto(datos["pagos"]["pago_para_no_generar_intereses"]),
        dia_corte=_dia(datos["fecha_corte"]),
        dia_limite_pago=_dia(datos["fecha_limite_pago"]),
    )
    msi = []
    for m in datos["movimientos"]:
        if m["modalidad"] == "msi":
            plan = m["meses"] or {}   # sin detalle del plan: los datos van en null
            msi.append(MsiExtraidoOut(descripcion=m["concepto"],
                                      monto_total=_monto(plan.get("monto_original")),
                                      meses=plan.get("meses_totales"),
                                      mensualidades_pagadas=plan.get("mensualidad_actual")))
    movimientos = [MovimientoExtraidoOut(fecha=m["fecha"], concepto=m["concepto"], monto=_monto(m["monto"]))
                   for m in datos["movimientos"]
                   if m["monto"] > 0 and m["modalidad"] != "msi" and m["tipo"] not in NO_SON_CARGOS]
    return EstadoCuentaExtraidoOut(tarjeta=tarjeta, msi=msi, movimientos=movimientos)
