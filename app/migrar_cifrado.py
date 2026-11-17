"""Migración para cifrar (o revertir) las columnas sensibles en una base que ya tiene datos (T53b).

    python -m app.migrar_cifrado --simular                       # no escribe: solo dice qué haría
    python -m app.migrar_cifrado --confirmo-respaldo             # cifra
    python -m app.migrar_cifrado --revertir --confirmo-respaldo  # vuelve a DECIMAL en claro

ANTES de correrla en una base real: respaldo (mysqldump), la llave guardada APARTE del respaldo, y
probarla en una copia. El procedimiento completo está en docs/CIFRADO.md. Sin `--confirmo-respaldo`
no escribe nada.

Qué hace, por orden:
  1. Foto de cada columna (filas, no nulos y suma), leyendo en claro o cifrado, como esté.
  2. Quita los CHECK que comparan montos (no se pueden evaluar sobre texto cifrado).
  3. ALTER de DECIMAL(12,2) a VARCHAR(96). Es DDL: MySQL lo confirma solo, por eso se detiene la API antes.
  4. En UNA transacción: cifra fila por fila lo que aún no empiece con `v1:`, lee todo de vuelta,
     compara con la foto del paso 1 y solo entonces confirma. Si algo no cuadra, revierte.
Se puede repetir sin riesgo: lo ya cifrado y lo ya convertido se salta.
"""
import argparse
import sys
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.core import cifrado
from app.core.cifrado import COLUMNAS_CIFRADAS, PREFIJO

# CHECK que comparan montos y hay que quitar. Los nombres difieren según cómo se creó la base
# (db/schema.sql o create_all con los modelos), así que se buscan los dos.
CHECKS_A_QUITAR = {
    "tarjeta": ("ck_tarjeta_limite_no_negativo", "ck_tarjeta_limite", "ck_tarjeta_saldo"),
    "deuda": ("ck_deuda_monto_original_positivo", "ck_deuda_saldo_no_negativo",
              "ck_deuda_monto", "ck_deuda_saldo"),
    "plan_msi": ("ck_plan_msi_monto_original_positivo", "ck_plan_msi_monto_mensualidad_positivo",
                 "ck_plan_msi_monto_coherente", "ck_msi_monto", "ck_msi_mensualidad"),
    "movimiento": ("ck_movimiento_monto_no_negativo",),
}
# Los que `--revertir` vuelve a crear: los de db/schema.sql (la definición de referencia)
CHECKS_AL_REVERTIR = {
    "tarjeta": (("ck_tarjeta_limite_no_negativo", "limite_credito >= 0"),),
    "deuda": (("ck_deuda_monto_original_positivo", "monto_original > 0"),
              ("ck_deuda_saldo_no_negativo", "saldo_actual >= 0")),
    "plan_msi": (("ck_plan_msi_monto_original_positivo", "monto_original > 0"),
                 ("ck_plan_msi_monto_mensualidad_positivo", "monto_mensualidad > 0"),
                 ("ck_plan_msi_monto_coherente",
                  "ABS(monto_original - monto_mensualidad * num_mensualidades) <= num_mensualidades * 0.01")),
    "movimiento": (("ck_movimiento_monto_no_negativo", "monto >= 0"),),
}
# Un CHECK que menciona una columna cifrada pero no compara su monto y puede quedarse
CHECKS_INOFENSIVOS = {"ck_movimiento_manual_sin_extraidos"}


class MigracionError(Exception):
    pass


def _tablas() -> dict[str, list[tuple[str, bool, Optional[str]]]]:
    por_tabla: dict[str, list] = {}
    for tabla, columna, nulo, defecto in COLUMNAS_CIFRADAS:
        por_tabla.setdefault(tabla, []).append((columna, nulo, defecto))
    return por_tabla


def _ctx(tabla: str, columna: str) -> str:
    return f"{tabla}.{columna}"


# ------------------------------------------------------------------ fotos y lecturas
def foto(conn: Connection) -> dict[str, tuple[int, int, Decimal]]:
    """{'tabla.columna': (filas, no nulos, suma)}: lo que debe seguir igual antes y después."""
    salida = {}
    for tabla, columnas in _tablas().items():
        nombres = ", ".join(c for c, _, _ in columnas)
        filas = conn.execute(text(f"SELECT {nombres} FROM {tabla}")).fetchall()
        for i, (columna, _, _) in enumerate(columnas):
            valores = [cifrado.a_decimal(f[i], _ctx(tabla, columna)) for f in filas if f[i] is not None]
            salida[_ctx(tabla, columna)] = (len(filas), len(valores), sum(valores, Decimal("0")))
    return salida


def _comparar(antes: dict, despues: dict) -> list[str]:
    return [f"{k}: antes {antes[k]} / después {despues[k]}" for k in antes if antes[k] != despues[k]]


# ------------------------------------------------------------------ datos
def transformar_filas(conn: Connection, cifrar: bool) -> int:
    """Cifra (o descifra) cada valor que aún no esté en el estado pedido. Devuelve cuántos tocó."""
    tocados = 0
    for tabla, columnas in _tablas().items():
        nombres = ", ".join(c for c, _, _ in columnas)
        for fila in conn.execute(text(f"SELECT id, {nombres} FROM {tabla}")).fetchall():
            cambios = {}
            for i, (columna, _, _) in enumerate(columnas, start=1):
                valor = fila[i]
                if valor is None:
                    continue
                cifrado_ya = isinstance(valor, str) and valor.startswith(PREFIJO)
                if cifrar and not cifrado_ya:
                    plano = cifrado.a_texto(cifrado.a_decimal(valor, _ctx(tabla, columna)), _ctx(tabla, columna))
                    cambios[columna] = cifrado.cifrar_texto(plano, _ctx(tabla, columna))
                elif not cifrar and cifrado_ya:
                    plano = cifrado.descifrar_texto(valor, _ctx(tabla, columna))
                    cambios[columna] = cifrado.a_texto(plano, _ctx(tabla, columna))
            if cambios:
                asignaciones = ", ".join(f"{c} = :{c}" for c in cambios)
                conn.execute(text(f"UPDATE {tabla} SET {asignaciones} WHERE id = :id"),
                             {**cambios, "id": fila[0]})
                tocados += len(cambios)
    return tocados


# ------------------------------------------------------------------ DDL (solo MySQL)
def _tipo(conn: Connection, tabla: str, columna: str) -> str:
    fila = conn.execute(text(
        "SELECT DATA_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"),
        {"t": tabla, "c": columna}).first()
    if fila is None:
        raise MigracionError(f"No existe {tabla}.{columna}")
    return str(fila[0]).lower()


def _checks(conn: Connection, tabla: str) -> dict[str, str]:
    filas = conn.execute(text(
        "SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS cc "
        "JOIN information_schema.TABLE_CONSTRAINTS tc "
        "  ON tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME "
        "WHERE tc.CONSTRAINT_SCHEMA = DATABASE() AND tc.TABLE_NAME = :t AND tc.CONSTRAINT_TYPE = 'CHECK'"),
        {"t": tabla}).fetchall()
    return {n: c for n, c in filas}


def ddl_adelante(conn: Connection, simular: bool) -> None:
    for tabla, columnas in _tablas().items():
        if all(_tipo(conn, tabla, c) in ("varchar", "char") for c, _, _ in columnas):
            print(f"  {tabla}: columnas ya son de texto, sin DDL")
            continue
        existentes = _checks(conn, tabla)
        quitar = [n for n in CHECKS_A_QUITAR.get(tabla, ()) if n in existentes]
        propias = [c for c, _, _ in columnas]
        resto = [n for n, clausula in existentes.items()
                 if n not in quitar and n not in CHECKS_INOFENSIVOS
                 and any(f"`{c}`" in clausula for c in propias)]
        if resto:
            raise MigracionError(f"{tabla}: hay CHECK que comparan columnas por cifrar y no sé quitar: {resto}. "
                                 "Revisa CHECKS_A_QUITAR.")
        print(f"  {tabla}: quitar CHECK {quitar or '(ninguno)'} y pasar {[c for c, _, _ in columnas]} a VARCHAR")
        if simular:
            continue
        for nombre in quitar:
            conn.execute(text(f"ALTER TABLE {tabla} DROP CHECK {nombre}"))
        modifica = ", ".join(f"MODIFY {c} VARCHAR({cifrado.LONGITUD_COLUMNA}) {'NULL' if nulo else 'NOT NULL'}"
                             for c, nulo, _ in columnas)
        conn.execute(text(f"ALTER TABLE {tabla} {modifica}"))


def ddl_atras(conn: Connection, simular: bool) -> None:
    for tabla, columnas in _tablas().items():
        if all(_tipo(conn, tabla, c) == "decimal" for c, _, _ in columnas):
            print(f"  {tabla}: columnas ya son DECIMAL, sin DDL")
            continue
        print(f"  {tabla}: pasar {[c for c, _, _ in columnas]} a DECIMAL(12,2) y recrear sus CHECK")
        if simular:
            continue
        modifica = ", ".join(
            f"MODIFY {c} DECIMAL(12,2) {'NULL' if nulo else 'NOT NULL'}"
            f"{' DEFAULT ' + defecto if defecto is not None else ''}" for c, nulo, defecto in columnas)
        conn.execute(text(f"ALTER TABLE {tabla} {modifica}"))
        existentes = _checks(conn, tabla)
        for nombre, clausula in CHECKS_AL_REVERTIR.get(tabla, ()):
            if nombre not in existentes:
                conn.execute(text(f"ALTER TABLE {tabla} ADD CONSTRAINT {nombre} CHECK ({clausula})"))


# ------------------------------------------------------------------ orquestación
def ejecutar(engine: Engine, revertir: bool = False, simular: bool = False, ddl: bool = True) -> None:
    """`ddl=False` salta los ALTER (para probar la parte de datos en SQLite)."""
    cifrado.verificar_llave()
    sentido = "REVERTIR (a claro)" if revertir else "CIFRAR"
    print(f"== {sentido}{' · SIMULACIÓN, no se escribe nada' if simular else ''} ==")

    with engine.connect() as conn:
        antes = foto(conn)
    print("Foto previa (filas, no nulos, suma):")
    for k, v in antes.items():
        print(f"  {k}: {v[0]} filas, {v[1]} con valor, suma {v[2]}")

    if revertir:
        # primero los datos (todavía en columnas de texto), luego el tipo
        with engine.begin() as conn:
            print("Descifrando datos…" if not simular else "Descifraría los datos")
            if not simular:
                n = transformar_filas(conn, cifrar=False)
                despues = foto(conn)
                if _comparar(antes, despues):
                    raise MigracionError("Las sumas no coinciden: " + "; ".join(_comparar(antes, despues)))
                print(f"  {n} valores descifrados")
        if ddl:
            with engine.connect() as conn:
                ddl_atras(conn, simular)
    else:
        if ddl:
            with engine.connect() as conn:
                ddl_adelante(conn, simular)
        if not simular:
            with engine.begin() as conn:   # una transacción: si algo no cuadra, no se confirma
                n = transformar_filas(conn, cifrar=True)
                despues = foto(conn)
                malas = _comparar(antes, despues)
                if malas:
                    raise MigracionError("Las sumas no coinciden, se revierte: " + "; ".join(malas))
                print(f"  {n} valores cifrados y verificados")

    with engine.connect() as conn:
        final = foto(conn) if not simular else antes
    if _comparar(antes, final):
        raise MigracionError("Las sumas finales no coinciden: " + "; ".join(_comparar(antes, final)))
    print("Listo: conteos y sumas idénticos a los de antes." if not simular else "Simulación terminada.")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simular", action="store_true", help="no escribe nada")
    ap.add_argument("--revertir", action="store_true", help="descifra y vuelve a DECIMAL")
    ap.add_argument("--confirmo-respaldo", action="store_true",
                    help="confirmo que hay respaldo reciente y la llave guardada aparte")
    args = ap.parse_args(argv)
    if not args.simular and not args.confirmo_respaldo:
        print("Para escribir hace falta --confirmo-respaldo (o usa --simular). Lee docs/CIFRADO.md.",
              file=sys.stderr)
        return 2
    from app.core.database import engine
    try:
        ejecutar(engine, revertir=args.revertir, simular=args.simular)
    except (MigracionError, cifrado.ErrorCifrado) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
