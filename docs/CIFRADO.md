# Cifrado de campos sensibles · T53b (IC-14, RNF-19)

Los montos sensibles se guardan **cifrados con AES-256-GCM** en la base de datos. La llave vive en una variable de entorno, nunca en el código ni en la base.

## Qué se cifra

| Tabla | Columnas |
|---|---|
| `tarjeta` | `limite_credito`, `saldo_actual` |
| `deuda` | `monto_original`, `saldo_actual`, `pago_mensual` |
| `plan_msi` | `monto_original`, `monto_mensualidad` |
| `estado_cuenta` | `saldo_al_corte`, `pago_minimo`, `pago_no_intereses` |
| `movimiento` | `monto`, `monto_extraido` |

**Quedan sin cifrar, a propósito:** `ingreso.monto` y `gasto.monto` (decisión de alcance del 17-nov: IC-14 pide saldos, límites y montos de deuda; los ingresos y gastos son lo que el usuario captura a mano y pesan menos si se filtran), las tasas, los días de corte y pago, los nombres de tarjetas y deudas, y `score_historial` (guarda proporciones, no saldos). Si se decide cifrar también ingresos y gastos, es agregar dos filas a `COLUMNAS_CIFRADAS` en `app/core/cifrado.py` y correr la migración.

`estado_cuenta` y `movimiento` todavía no los escribe ningún endpoint; ya están listos para cuando exista `/estados-cuenta/confirmar`.

## Cómo funciona

- `app/core/cifrado.py`. Cada valor se guarda como `v1:` + base64(nonce de 12 bytes ‖ texto cifrado ‖ etiqueta). El nonce es aleatorio: el mismo monto da un resultado distinto cada vez.
- Es transparente para el resto del código: el tipo `DineroCifrado` (`app/models/finanzas.py`) cifra al escribir y devuelve `Decimal` al leer. Los servicios, el score, la proyección y el priorizador no cambiaron.
- Cada columna tiene su **contexto** (`tarjeta.saldo_actual`) como dato autenticado: un valor copiado a otra columna no descifra. Un valor alterado tampoco (la etiqueta GCM lo detecta).
- El prefijo `v1:` permite rotar la llave o el formato más adelante.
- Un valor **sin** prefijo se lee como número en claro. Es lo que hace segura la migración (se puede repetir o interrumpir) y no es un modo de operación: la API siempre escribe cifrado.
- **Sin `CIFRADO_LLAVE` válida la API no arranca**, para no guardar nada en claro por descuido.

## La llave

```sh
python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Va en `CIFRADO_LLAVE` del `.env` del servidor (el `.env.example` ya la lista). Reglas:

- **Guárdala aparte del respaldo de la base** (gestor de contraseñas, bóveda). Un respaldo sin la llave no sirve para nada, y una llave perdida significa **datos perdidos para siempre**: no hay forma de recuperarlos.
- Una llave distinta para producción y para desarrollo. No se sube al repositorio.
- Cambiar la llave de una base ya cifrada **rompe la lectura**: hay que descifrar con la vieja y volver a cifrar con la nueva (hoy no hay un comando para rotar; es la misma migración con las dos llaves, y queda como pendiente).

## Lo que cambia para quien programa

- **No se puede filtrar, ordenar ni sumar por estas columnas en SQL** (`WHERE saldo_actual > …`, `ORDER BY`, `SUM`). Revisado el 17-nov: ninguna consulta de la app lo hace; todo cálculo se hace en Python sobre los objetos (proyección, score, priorizador). Un `ORDER BY` nuevo sobre estas columnas ordenaría texto cifrado sin sentido.
- **Sin CHECK de monto en la base** para estas columnas (no se pueden evaluar sobre texto cifrado): `limite_credito >= 0`, `saldo_actual >= 0`, `monto_original > 0`, `monto_mensualidad > 0`, el de coherencia del plan MSI y `movimiento.monto >= 0`. La validación vive en los esquemas Pydantic y en `services/msi.validar_plan`, y las pruebas de `tests/api/test_revision_t54.py` comprueban que el servidor las aplica. `estado_cuenta` y `movimiento` no tienen endpoint de escritura, así que quien lo agregue debe validar ahí.
- Los reportes a mano en SQL ya no ven montos. Para inspeccionar datos hay que pasar por la app.
- Los datos de `seed_demo.py` se cifran como cualquier otro: necesita `CIFRADO_LLAVE`.

## Migración de una base con datos

```sh
docker compose exec api python -m app.migrar_cifrado --simular                       # solo dice qué haría
docker compose exec api python -m app.migrar_cifrado --confirmo-respaldo             # cifra
docker compose exec api python -m app.migrar_cifrado --revertir --confirmo-respaldo  # vuelve a claro
```

Qué hace, en orden: foto de cada columna (filas, no nulos, suma) → quita los CHECK de monto → `ALTER` a `VARCHAR(96)` → **en una sola transacción** cifra fila por fila, vuelve a leer todo y compara con la foto; si algo no cuadra, revierte. Es repetible: lo ya cifrado se salta. `--revertir` hace el camino inverso y recrea los CHECK de `db/schema.sql`.

### Procedimiento para la base real

El `ALTER` de MySQL no es transaccional, así que **la API va detenida** mientras corre. Es lo más riesgoso de la entrega: sigue el orden.

1. **Genera la llave** y guárdala aparte (ver arriba). Ponla en el `.env`.
2. **Respaldo:** `docker compose exec db mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --no-tablespaces ikamoney > respaldo-antes-de-cifrar.sql`. Comprueba que el archivo pesa algo y guárdalo fuera del servidor.
3. **Prueba en una copia primero:** levanta un MySQL aparte, carga el respaldo y corre la migración ahí (`--simular`, luego real, luego `--revertir`). Compara con el recorrido de números del perfil de T25 (score 78, flujo 3,838.00, acumulado 8,838.00).
4. **En la base real:** `docker compose stop api` → `--simular` → `--confirmo-respaldo` → `docker compose up -d api` (con el código nuevo y la llave en el `.env`).
5. **Verifica:** `SELECT saldo_actual FROM tarjeta LIMIT 3;` debe mostrar `v1:…`; entra a la app y revisa que el balance y el score den lo de antes.
6. **Si algo sale mal:** `--revertir --confirmo-respaldo` (o restaura el respaldo) y vuelve al código anterior.

Efecto secundario conocido: la migración actualiza `actualizado_en` de las filas que toca (MySQL lo hace solo).

### Base nueva

`db/schema.sql` ya crea estas columnas como `VARCHAR(96)` sin CHECK de monto, así que una base nueva no necesita migración, solo la llave. Con `crear_tablas` (producción) los modelos hacen lo mismo.

## Verificación hecha (17-nov-2026)

En un MySQL 8.0 desechable, creado con el `schema.sql` anterior y con datos de ejemplo (NULL, centavos, una tarjeta con límite 0):

| Paso | Resultado |
|---|---|
| `--simular` | No escribió; listó los CHECK correctos de cada tabla |
| Migración real | 18 valores cifrados; en la base `tarjeta.saldo_actual` pasó a `varchar(96)` con `v1:…`, los `NULL` siguieron siendo `NULL`; conteos y sumas idénticos |
| La app sobre la base migrada | El ORM leyó los `Decimal` correctos, el motor de balance los usó, un `INSERT` nuevo funcionó con los CHECK ya quitados |
| Repetirla | 0 valores tocados |
| `--revertir` | `DECIMAL(12,2)` otra vez, CHECK recreados; el volcado coincide con el original salvo `actualizado_en` |
| `schema.sql` nuevo en un MySQL limpio | Carga sin errores: 13 tablas y las 12 columnas en `varchar(96)` |

Las pruebas de `pytest` (SQLite) cubren la parte de datos de la migración, la ida y vuelta, el aislamiento de la llave y que la API responde lo mismo con la base cifrada o en claro; **no cubren el DDL**, que solo se probó en MySQL como arriba. Con la suite completa: `tests/unit/test_cifrado.py` y `tests/api/test_cifrado_datos.py`.

## Pendiente

- Rotación de llave (comando que descifre con la vieja y cifre con la nueva).
- Cifrado de `ingreso.monto` y `gasto.monto`, si el equipo lo decide.
- Cifrado en reposo del volumen y de los respaldos de MySQL, que es otra capa: este cifrado protege los campos, no los nombres ni las fechas.
