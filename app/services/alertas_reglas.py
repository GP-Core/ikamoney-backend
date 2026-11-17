"""Reglas de alertas AL-01 a AL-04 (T47): matemática pura, sin base de datos ni FastAPI.

Recibe lo que ya calculan el balance (T33) y el score (T35) y decide qué avisar. Los umbrales y los
textos viven en app/core/reglas_alertas.json. Los textos nunca incluyen saldos ni montos (IC-07).
"""
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

RUTA_REGLAS = Path(__file__).resolve().parents[1] / "core" / "reglas_alertas.json"
CERO = Decimal("0")
_CIEN = Decimal("100")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")


@dataclass(frozen=True)
class ReglasAlertas:
    version: str
    defecto: dict
    rangos: dict
    horizonte_meses: int
    enfriamiento_horas: int
    ventana_aviso_horas: int
    textos: dict


@lru_cache(maxsize=1)
def reglas_vigentes() -> ReglasAlertas:
    with open(RUTA_REGLAS, encoding="utf-8") as f:
        d = json.load(f)
    return ReglasAlertas(version=d["version_reglas"], defecto=d["defecto"], rangos=d["rangos"],
                         horizonte_meses=d["horizonte_meses"],
                         enfriamiento_horas=d["enfriamiento_horas"],
                         ventana_aviso_horas=d["ventana_aviso_horas"], textos=d["reglas"])


@dataclass(frozen=True)
class Configuracion:
    umbral_utilizacion: int
    dias_anticipacion: int
    canal_correo: bool
    canal_push: bool


@dataclass(frozen=True)
class MesDatos:
    periodo: str            # 'AAAA-MM'
    ingresos: Decimal
    compromisos: Decimal


@dataclass(frozen=True)
class TarjetaDatos:
    id: int
    nombre: str
    saldo: Decimal
    limite: Decimal
    pendiente_msi: Decimal
    fecha_pago: date        # próxima fecha límite de pago


@dataclass(frozen=True)
class DatosAlertas:
    hoy: date
    meses: tuple[MesDatos, ...]
    tarjetas: tuple[TarjetaDatos, ...]


@dataclass(frozen=True)
class Hallazgo:
    regla: str
    referencia: str
    severidad: str
    titulo: str
    mensaje: str
    accion: str

    @property
    def clave(self) -> str:
        return f"{self.regla}|{self.referencia}"


def utilizacion(t: TarjetaDatos) -> Decimal:
    """(saldo + MSI pendiente) / límite en %; con límite 0 y deuda, infinito (Fórmula 4 de T25)."""
    usado = t.saldo + t.pendiente_msi
    if t.limite > 0:
        return usado / t.limite * _CIEN
    return Decimal("Infinity") if usado > 0 else CERO


def nombre_mes(periodo: str) -> str:
    anio, mes = periodo.split("-")
    return f"{MESES[int(mes) - 1]} de {anio}"


def _hallazgo(reglas: ReglasAlertas, regla: str, referencia: str, **valores) -> Hallazgo:
    t = reglas.textos[regla]
    return Hallazgo(regla=regla, referencia=referencia, severidad=t["severidad"],
                    titulo=t["titulo"].format(**valores), mensaje=t["mensaje"].format(**valores),
                    accion=t["accion"].format(**valores))


def evaluar(datos: DatosAlertas, config: Configuracion, reglas: ReglasAlertas) -> list[Hallazgo]:
    """Todas las alertas que aplican hoy. No sabe nada de cuáles ya existen: eso lo decide el servicio."""
    salida: list[Hallazgo] = []

    # AL-01 (RF-64): algún mes con compromisos mayores que los ingresos. Una sola alerta, con el
    # primer mes. Sin ningún ingreso registrado no se avisa: ya lo dice el balance (SIN_INGRESOS).
    if any(m.ingresos > 0 for m in datos.meses):
        for m in datos.meses:
            if m.compromisos > m.ingresos:
                salida.append(_hallazgo(reglas, "AL-01", "proyeccion", mes=nombre_mes(m.periodo)))
                break

    for t in datos.tarjetas:
        usada = utilizacion(t)
        ref = f"tarjeta:{t.id}"
        if usada > _CIEN:                                                     # AL-04 (CE-10)
            salida.append(_hallazgo(reglas, "AL-04", ref, tarjeta=t.nombre))
        elif usada >= config.umbral_utilizacion:                              # AL-02 (RF-65)
            salida.append(_hallazgo(reglas, "AL-02", ref, tarjeta=t.nombre,
                                    umbral=config.umbral_utilizacion))
        dias = (t.fecha_pago - datos.hoy).days
        if t.saldo > 0 and 0 <= dias <= config.dias_anticipacion:             # AL-03
            salida.append(_hallazgo(reglas, "AL-03", f"{ref}:{t.fecha_pago.isoformat()}",
                                    tarjeta=t.nombre,
                                    fecha=f"{t.fecha_pago.day} de {MESES[t.fecha_pago.month - 1]}"))
    return salida
