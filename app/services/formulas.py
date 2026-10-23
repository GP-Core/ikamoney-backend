"""Fórmulas 1, 2 y 3 de T25 (proyección financiera), más las fórmulas 5 y 6 que la proyección
necesita para el interés y el pago mínimo de cada tarjeta.

Este módulo es puro: no conoce la base de datos ni FastAPI. Recibe números y devuelve números,
así se puede comparar directamente con la hoja de referencia de T26.

Convenciones de T25:
- Los cálculos intermedios usan precisión completa (Decimal); solo el resultado que se muestra
  se redondea a 2 decimales (eso lo hace el servicio al armar la respuesta).
- El mes 1 es el mes en curso. Tasa mensual = tasa anual ÷ 12. IVA de 16 % sobre los intereses.
- Las tasas se reciben como decimal: 0.60 = 60 %.
- Sin compras nuevas con tarjeta. El usuario paga el mínimo salvo que indique otro pago.
"""
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from typing import Optional

# ----------------------------------------------------------- constantes de T25
IVA = Decimal("0.16")
PCT_SALDO_MIN = Decimal("0.015")     # pago mínimo (a): 1.5 % del saldo + intereses (Banxico)
PCT_LINEA_MIN = Decimal("0.0125")    # pago mínimo (b): 1.25 % de la línea de crédito (Banxico)
UMBRAL_SALDO_CERO = Decimal("0.005")  # un saldo menor o igual se considera liquidado
HORIZONTE_DEFECTO = 12
HORIZONTE_MIN = 3
HORIZONTE_MAX = 24

CERO = Decimal("0")
_DOCE = Decimal("12")
_PRECISION = 34                      # dígitos de precisión para los cálculos intermedios


# ------------------------------------------------------------------- entradas
@dataclass(frozen=True)
class TarjetaEntrada:
    id: int
    nombre: str
    saldo: Decimal                   # saldo revolvente sin MSI (saldo_k)
    limite: Decimal                  # limite_k
    tasa_anual: Decimal              # tasa_anual_k sin IVA, en decimal (0.60 = 60 %)
    pago_planeado: Optional[Decimal] = None   # pago_usuario_k; None = pago mínimo


@dataclass(frozen=True)
class MsiEntrada:
    id: int
    descripcion: str
    monto: Decimal                   # monto_msi_j
    plazo: int                       # plazo_msi_j
    pagadas: int                     # pagadas_msi_j
    mensualidad: Optional[Decimal] = None     # la guardada en la base; None = Fórmula 1


@dataclass(frozen=True)
class DeudaEntrada:
    id: int
    nombre: str
    saldo: Decimal
    pago_mensual: Decimal            # otras_cuotas de esta deuda
    tasa_anual: Decimal = CERO       # en decimal; 0 si no se conoce


@dataclass(frozen=True)
class EntradaProyeccion:
    """Una lista por concepto con el monto de cada mes (índice 0 = mes 1).

    Ingresos y gastos fijos van mes por mes porque los recurrentes semanales o quincenales no
    caen igual cada mes. Si todas las listas tienen el mismo valor se obtiene exactamente la
    Fórmula 3 de T25 con ingreso, gastos fijos y variables constantes.
    """
    ingresos: list[Decimal]
    gastos_fijos: list[Decimal]
    gastos_variables: list[Decimal]
    ahorro_inicial: Decimal = CERO
    tarjetas: list[TarjetaEntrada] = field(default_factory=list)
    planes_msi: list[MsiEntrada] = field(default_factory=list)
    deudas: list[DeudaEntrada] = field(default_factory=list)


# -------------------------------------------------------------------- salidas
@dataclass(frozen=True)
class TarjetaMes:
    tarjeta_id: int
    nombre: str
    saldo_inicio: Decimal
    interes: Decimal
    pago: Decimal
    saldo_fin: Decimal


@dataclass(frozen=True)
class MesProyectado:
    mes: int
    ingresos: Decimal
    gastos_fijos: Decimal
    gastos_variables: Decimal
    pagos_tarjetas: Decimal
    mensualidades_msi: Decimal
    otras_cuotas: Decimal
    flujo: Decimal
    acumulado: Decimal
    msi_activos: int
    tarjetas: list[TarjetaMes]

    @property
    def compromisos(self) -> Decimal:
        """Pagos de tarjetas + mensualidades MSI + otras cuotas."""
        return self.pagos_tarjetas + self.mensualidades_msi + self.otras_cuotas

    @property
    def saldo_tarjetas(self) -> Decimal:
        """Lo que se sigue debiendo en las tarjetas al terminar el mes (sin MSI)."""
        return sum((t.saldo_fin for t in self.tarjetas), CERO)


@dataclass(frozen=True)
class Proyeccion:
    meses: list[MesProyectado]

    @property
    def flujo_minimo(self) -> Decimal:
        return min(m.flujo for m in self.meses)

    @property
    def acumulado_minimo(self) -> Decimal:
        return min(m.acumulado for m in self.meses)

    @property
    def meses_en_negativo(self) -> int:
        """Meses con acumulado negativo (el indicador de T26)."""
        return sum(1 for m in self.meses if m.acumulado < 0)


# ------------------------------------------------- Fórmula 1: MSI
def mensualidad_msi(monto: Decimal, plazo: int) -> Decimal:
    """Mensualidad = monto_msi / plazo_msi."""
    return monto / plazo


def pendiente_msi(mensualidad: Decimal, plazo: int, pagadas: int) -> Decimal:
    """Pendiente = Mensualidad × (plazo_msi − pagadas_msi)."""
    return mensualidad * max(plazo - pagadas, 0)


def msi_activo_en_mes(plazo: int, pagadas: int, mes: int) -> bool:
    """El plan cobra en el mes t si pagadas + t ≤ plazo (CE-07: en su última mensualidad solo
    cuenta en el mes 1)."""
    return pagadas + mes <= plazo


def _mensualidad(plan: MsiEntrada) -> Decimal:
    return plan.mensualidad if plan.mensualidad is not None else mensualidad_msi(plan.monto, plan.plazo)


# --------------------------------------- Fórmulas 5 y 6: interés y pago mínimo
def tasa_mensual_efectiva(tasa_anual: Decimal) -> Decimal:
    """r' = tasa anual / 12 × (1 + IVA)."""
    return tasa_anual / _DOCE * (1 + IVA)


def interes_mes(saldo: Decimal, tasa_anual: Decimal) -> Decimal:
    """Interés del mes con IVA. Un saldo liquidado no genera intereses."""
    if saldo <= UMBRAL_SALDO_CERO:
        return CERO
    return saldo * tasa_mensual_efectiva(tasa_anual)


def pago_minimo(saldo: Decimal, interes: Decimal, limite: Decimal) -> Decimal:
    """Regla de Banxico: el mayor entre (a) 1.5 % del saldo + interés y (b) 1.25 % de la línea,
    sin pasar de saldo + interés (CE-01)."""
    if saldo <= UMBRAL_SALDO_CERO:
        return CERO
    opcion_a = PCT_SALDO_MIN * saldo + interes
    opcion_b = PCT_LINEA_MIN * limite
    return min(max(opcion_a, opcion_b), saldo + interes)


def pago_tarjeta(saldo: Decimal, interes: Decimal, limite: Decimal,
                 pago_planeado: Optional[Decimal]) -> Decimal:
    """Pago_k,t: el que planea el usuario (sin pasar de lo que debe) o, si no lo indica, el mínimo."""
    if saldo <= UMBRAL_SALDO_CERO:
        return CERO
    if pago_planeado is None:
        return pago_minimo(saldo, interes, limite)
    return min(pago_planeado, saldo + interes)


# --------------------------------------------- Fórmulas 2 y 3: proyección
def proyectar(entrada: EntradaProyeccion, meses: int = HORIZONTE_DEFECTO) -> Proyeccion:
    """Proyección mes por mes.

    Fórmula 2: Saldo_k,t+1 = Saldo_k,t + Interés_k,t − Pago_k,t
    Fórmula 3: Flujo_t = ingreso − gastos_fijos − gastos_variables − ΣPago_k,t
                        − ΣMensualidad_j,t − otras_cuotas
               Acumulado_t = Acumulado_t−1 + Flujo_t, con Acumulado_0 = ahorro_inicial
    """
    if not HORIZONTE_MIN <= meses <= HORIZONTE_MAX:
        raise ValueError(f"El horizonte debe estar entre {HORIZONTE_MIN} y {HORIZONTE_MAX} meses.")
    for nombre in ("ingresos", "gastos_fijos", "gastos_variables"):
        if len(getattr(entrada, nombre)) < meses:
            raise ValueError(f"'{nombre}' debe tener un valor por cada mes proyectado.")

    with localcontext() as ctx:
        ctx.prec = _PRECISION
        saldos = {t.id: t.saldo for t in entrada.tarjetas}
        saldos_deuda = {d.id: d.saldo for d in entrada.deudas}
        acumulado = entrada.ahorro_inicial
        resultado: list[MesProyectado] = []

        for t in range(1, meses + 1):
            # Tarjetas: interés, pago y nuevo saldo (Fórmulas 5, 6 y 2)
            detalle: list[TarjetaMes] = []
            for k in entrada.tarjetas:
                saldo = saldos[k.id]
                interes = interes_mes(saldo, k.tasa_anual)
                pago = pago_tarjeta(saldo, interes, k.limite, k.pago_planeado)
                saldos[k.id] = saldo + interes - pago
                detalle.append(TarjetaMes(k.id, k.nombre, saldo, interes, pago, saldos[k.id]))
            pagos_tarjetas = sum((d.pago for d in detalle), CERO)

            # MSI vigentes en el mes t (Fórmula 1 y CE-07)
            activos = [p for p in entrada.planes_msi if msi_activo_en_mes(p.plazo, p.pagadas, t)]
            mensualidades = sum((_mensualidad(p) for p in activos), CERO)

            # Otras cuotas: cada deuda paga su cuota mientras tenga saldo (ver supuestos)
            cuotas = CERO
            for d in entrada.deudas:
                saldo = saldos_deuda[d.id]
                if saldo <= UMBRAL_SALDO_CERO:
                    continue
                interes = saldo * d.tasa_anual / _DOCE
                cuota = min(d.pago_mensual, saldo + interes)
                saldos_deuda[d.id] = saldo + interes - cuota
                cuotas += cuota

            ingresos = entrada.ingresos[t - 1]
            fijos = entrada.gastos_fijos[t - 1]
            variables = entrada.gastos_variables[t - 1]
            flujo = ingresos - fijos - variables - pagos_tarjetas - mensualidades - cuotas
            acumulado = acumulado + flujo

            resultado.append(MesProyectado(
                mes=t, ingresos=ingresos, gastos_fijos=fijos, gastos_variables=variables,
                pagos_tarjetas=pagos_tarjetas, mensualidades_msi=mensualidades,
                otras_cuotas=cuotas, flujo=flujo, acumulado=acumulado,
                msi_activos=len(activos), tarjetas=detalle))

    return Proyeccion(meses=resultado)


def estimar_gastos_variables(totales_meses_previos: list[Decimal]) -> Optional[Decimal]:
    """Gastos variables estimados (supuesto de T25): promedio de los últimos 3 meses que tienen
    registros. Recibe el total de cada uno de los 3 meses anteriores; los meses en cero no
    cuentan. Devuelve None si no hay historial (se usa entonces lo que el usuario capture)."""
    con_registros = [t for t in totales_meses_previos[-3:] if t > 0]
    if not con_registros:
        return None
    return sum(con_registros, CERO) / len(con_registros)


def constante(valor: Decimal, meses: int) -> list[Decimal]:
    """El mismo monto para cada mes (como en T25: ingreso y gastos mensuales fijos)."""
    return [valor] * meses