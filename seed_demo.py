"""
Carga de datos de prueba de IKAMONEY (perfil de T25/T26) usando los endpoints reales.

Que hace:
  1. Crea el usuario demo (demo@ikamoney.dev) si no existe y genera su token JWT.
  2. Detecta las rutas de la API leyendo /openapi.json (no hay que escribirlas a mano).
  3. Crea: 2 tarjetas, 2 planes MSI, 1 ingreso, 1 gasto fijo y 1 gasto variable.
  4. Consulta la proyeccion y comprueba que el mes 1 de flujo 3,838 y acumulado 8,838.
  5. Imprime el token y el comando para dejarlo en el navegador del frontend.

Se puede repetir sin duplicar: lo que ya existe se omite.

Uso (PowerShell, desde la carpeta ikamoney-backend, con Docker corriendo):
    Get-Content seed_demo.py -Raw | docker compose exec -T api python -

Opciones (se pasan despues del guion):
    ... | docker compose exec -T api python - --con-deuda    agrega un prestamo de ejemplo
    ... | docker compose exec -T api python - --solo-token   solo imprime un token nuevo

Nota: --con-deuda cambia los numeros de la proyeccion, asi que ya no coincidiran con T26.
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import date

BASE = "http://localhost:8000"          # la API vista desde dentro del contenedor
CORREO = "demo@ikamoney.dev"
AHORRO_INICIAL = 5000
ESPERADO_MES1 = {"flujo": 3838.0, "acumulado": 8838.0}

CON_DEUDA = "--con-deuda" in sys.argv
SOLO_TOKEN = "--solo-token" in sys.argv


# --------------------------------------------------------------------------- usuario y token
def obtener_token() -> str:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.core.seguridad import crear_token
    from app.models import Usuario

    with SessionLocal() as db:
        usuario = db.execute(select(Usuario).where(Usuario.correo == CORREO)).scalars().first()
        if usuario is None:
            usuario = Usuario(nombre="Demo", correo=CORREO, contrasena_hash="no-usar")
            db.add(usuario)
            db.commit()
            db.refresh(usuario)
            print(f"Usuario demo creado (id {usuario.id}).")
        else:
            print(f"Usuario demo ya existia (id {usuario.id}).")
        return crear_token(usuario.id)


# --------------------------------------------------------------------------- HTTP
TOKEN = ""


def llamar(metodo: str, ruta: str, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(
        BASE + ruta,
        data=datos,
        method=metodo,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            texto = r.read().decode()
            return json.loads(texto) if texto else None
    except urllib.error.HTTPError as e:
        detalle = e.read().decode()
        raise SystemExit(f"\nERROR {e.code} en {metodo} {ruta}\n  cuerpo enviado: {cuerpo}\n  respuesta: {detalle}")
    except urllib.error.URLError as e:
        raise SystemExit(f"\nNo se pudo conectar con la API en {BASE}: {e}")


# --------------------------------------------------------------------------- deteccion de rutas
OPENAPI = {}


def resolver(esquema: dict) -> dict:
    """Sigue $ref / allOf / anyOf hasta llegar a un esquema con propiedades o enum."""
    if not isinstance(esquema, dict):
        return {}
    if "$ref" in esquema:
        nombre = esquema["$ref"].split("/")[-1]
        return resolver(OPENAPI["components"]["schemas"].get(nombre, {}))
    for clave in ("allOf", "anyOf", "oneOf"):
        if clave in esquema:
            for sub in esquema[clave]:
                r = resolver(sub)
                if r.get("properties") or r.get("enum"):
                    return r
    return esquema


def propiedades_post(operacion: dict) -> dict:
    try:
        cuerpo = operacion["requestBody"]["content"]["application/json"]["schema"]
    except KeyError:
        return {}
    return resolver(cuerpo).get("properties", {})


def buscar_post(requeridas: set, nombre: str):
    for ruta, item in OPENAPI["paths"].items():
        op = item.get("post")
        if op and requeridas <= set(propiedades_post(op)):
            return ruta, propiedades_post(op)
    raise SystemExit(f"No encontre en /openapi.json el endpoint POST de {nombre} (campos {sorted(requeridas)}).")


def buscar_get(fragmento: str, nombre: str) -> str:
    for ruta, item in OPENAPI["paths"].items():
        if "get" in item and fragmento in ruta and "{" not in ruta:
            return ruta
    raise SystemExit(f"No encontre en /openapi.json el endpoint GET de {nombre}.")


def valores_enum(propiedad: dict) -> list:
    r = resolver(propiedad)
    return list(r.get("enum", []))


def elegir(valores: list, preferido: str, contiene: str = None) -> str:
    if not valores or preferido in valores:
        return preferido
    if contiene:
        for v in valores:
            if contiene in str(v):
                return v
    return valores[0]


def listar(ruta: str) -> list:
    try:
        datos = llamar("GET", ruta)
    except SystemExit:
        return []
    if isinstance(datos, dict):
        for k in ("items", "datos", "data", "resultados"):
            if isinstance(datos.get(k), list):
                return datos[k]
        return []
    return datos or []


def crear_si_falta(ruta: str, cuerpo: dict, campo: str, etiqueta: str) -> dict:
    """POST solo si no hay un registro con el mismo valor en `campo`. Devuelve el registro."""
    for fila in listar(ruta):
        if isinstance(fila, dict) and fila.get(campo) == cuerpo[campo]:
            print(f"  = {etiqueta}: ya existe (id {fila.get('id')}), se omite.")
            return fila
    creado = llamar("POST", ruta, cuerpo)
    print(f"  + {etiqueta}: creado (id {creado.get('id')}).")
    return creado


# --------------------------------------------------------------------------- principal
def main():
    global TOKEN, OPENAPI
    TOKEN = obtener_token()

    if SOLO_TOKEN:
        mostrar_token()
        return

    OPENAPI = json.loads(urllib.request.urlopen(BASE + "/openapi.json", timeout=30).read().decode())

    ruta_tarjetas, _ = buscar_post({"limite_credito", "dia_corte", "tasa_anual"}, "tarjetas")
    ruta_msi, _ = buscar_post({"num_mensualidades", "tarjeta_id"}, "planes MSI")
    ruta_mov, props_mov = buscar_post({"concepto", "frecuencia", "monto", "tipo"}, "ingresos y gastos")
    ruta_cat = buscar_get("categorias", "categorias")

    frec = valores_enum(props_mov.get("frecuencia", {}))
    tipos = valores_enum(props_mov.get("tipo", {}))
    clases = valores_enum(props_mov.get("clase", {}))
    mensual = elegir(frec, "mensual", "mensual")
    unico = elegir(frec, "unico", "unic")
    t_ingreso = elegir(tipos, "ingreso", "ingres")
    t_gasto = elegir(tipos, "gasto", "gast")
    c_fijo = elegir(clases, "fijo", "fij")
    c_variable = elegir(clases, "variable", "variab")

    cat = {c["nombre"]: c["id"] for c in listar(ruta_cat)}
    for requerida in ("Vivienda", "Alimentaci\u00f3n", "Compras"):
        if requerida not in cat:
            raise SystemExit(f"Falta la categoria {requerida}. Corre antes: docker compose exec api python -m app.crear_tablas")

    hoy = date.today()
    primero = hoy.replace(day=1)

    print("\nTarjetas")
    tarjeta_a = crear_si_falta(ruta_tarjetas, {
        "nombre": "Tarjeta A", "banco": "Banco A", "ultimos_4": "1111",
        "limite_credito": 60000, "saldo_actual": 20000,
        "dia_corte": 5, "dia_pago": 25, "tasa_anual": 60, "activa": True,
    }, "nombre", "Tarjeta A")
    tarjeta_b = crear_si_falta(ruta_tarjetas, {
        "nombre": "Tarjeta B", "banco": "Banco B", "ultimos_4": "2222",
        "limite_credito": 30000, "saldo_actual": 12000,
        "dia_corte": 10, "dia_pago": 28, "tasa_anual": 45, "activa": True,
    }, "nombre", "Tarjeta B")

    print("\nPlanes MSI")
    crear_si_falta(ruta_msi, {
        "tarjeta_id": tarjeta_a["id"], "categoria_id": cat["Compras"], "descripcion": "MSI 1",
        "monto_original": 12000, "num_mensualidades": 12, "mensualidades_pagadas": 4,
        "monto_mensualidad": 1000, "fecha_compra": "2026-06-15",
    }, "descripcion", "MSI 1 (12 meses, 4 pagadas)")
    crear_si_falta(ruta_msi, {
        "tarjeta_id": tarjeta_b["id"], "categoria_id": cat["Compras"], "descripcion": "MSI 2",
        "monto_original": 6000, "num_mensualidades": 6, "mensualidades_pagadas": 3,
        "monto_mensualidad": 1000, "fecha_compra": "2026-07-15",
    }, "descripcion", "MSI 2 (6 meses, 3 pagadas)")

    print("\nIngresos y gastos")
    crear_si_falta(ruta_mov, {
        "tipo": t_ingreso, "concepto": "Sueldo", "monto": 20000, "frecuencia": mensual,
        "fecha": primero.isoformat(), "fecha_fin": None, "activo": True,
    }, "concepto", "Ingreso mensual 20,000")
    crear_si_falta(ruta_mov, {
        "tipo": t_gasto, "concepto": "Renta y servicios", "monto": 8000, "frecuencia": mensual,
        "fecha": primero.isoformat(), "fecha_fin": None,
        "categoria_id": cat["Vivienda"], "clase": c_fijo, "activo": True,
    }, "concepto", "Gasto fijo 8,000")
    crear_si_falta(ruta_mov, {
        "tipo": t_gasto, "concepto": "Gastos variables", "monto": 4000, "frecuencia": unico,
        "fecha": hoy.isoformat(), "fecha_fin": None,
        "categoria_id": cat["Alimentaci\u00f3n"], "clase": c_variable, "activo": True,
    }, "concepto", "Gasto variable 4,000 (este mes)")

    if CON_DEUDA:
        print("\nDeuda (opcional)")
        ruta_deuda, props_deuda = buscar_post({"acreedor", "pago_mensual"}, "deudas")
        tipos_deuda = valores_enum(props_deuda.get("tipo", {}))
        crear_si_falta(ruta_deuda, {
            "nombre": "Pr\u00e9stamo de ejemplo", "acreedor": "Banco C",
            "tipo": elegir(tipos_deuda, "prestamo_personal", "prestamo"),
            "monto_original": 30000, "saldo_actual": 24000, "tasa_anual": 30,
            "pago_mensual": 1500, "dia_pago": 15, "fecha_inicio": "2026-01-15",
        }, "nombre", "Pr\u00e9stamo de ejemplo")

    verificar()
    mostrar_token()


def verificar():
    print("\nVerificacion de la proyeccion")
    ruta = buscar_get("proyeccion", "proyeccion")
    r = llamar("GET", f"{ruta}?meses=12&ahorro_inicial={AHORRO_INICIAL}")
    mes1 = (r.get("proyeccion") or [{}])[0]
    print(f"  estado: {r.get('estado')}")
    print(f"  mes 1 ({mes1.get('periodo')}): flujo {mes1.get('flujo')}, acumulado {mes1.get('acumulado')}")
    if CON_DEUDA:
        print("  (con --con-deuda los valores ya no coinciden con T26; es normal)")
    elif (mes1.get("flujo"), mes1.get("acumulado")) == (ESPERADO_MES1["flujo"], ESPERADO_MES1["acumulado"]):
        print("  OK: coincide con T26 (flujo 3,838.00 y acumulado 8,838.00).")
    else:
        print(f"  OJO: se esperaba {ESPERADO_MES1}. Revisa que no haya datos de pruebas anteriores "
              "(docker compose down -v borra la base) o que tasa_anual use porcentaje (60, no 0.60).")


def mostrar_token():
    print("\n" + "=" * 70)
    print("TOKEN (dura 24 horas):\n")
    print(TOKEN)
    print("\nEn el navegador, con el frontend abierto (F12 > Console):\n")
    print(f"localStorage.setItem('ikamoney_token', '{TOKEN}')")
    print("\nLuego recarga con F5. Si Chrome bloquea el pegado, escribe: allow pasting")
    print("=" * 70)


main()
