# Implementación de T27 y T29: finanzas y flujo de efectivo

Documento de referencia de los endpoints de **tarjetas, deudas y planes MSI** (T29) y de **ingresos, gastos y categorías** (T27). Sigue el contrato de T17 (§4.2 y §4.3) y el esquema de datos de T18 (modelo ER y diccionario).

Todo vive bajo `/api/v1`, usa JWT `Bearer` (el `sub` es el id del usuario) y responde los errores con el formato de T17. Swagger: `http://localhost:8000/docs`.

---

## 1. Alcance

| Tarea | Recursos | Rutas |
| --- | --- | --- |
| T29 | Tarjetas, deudas, planes MSI | `/tarjetas`, `/deudas`, `/msi` |
| T27 | Ingresos y gastos (fijos y variables), categorías | `/movimientos`, `/categorias` |

Total: **23 endpoints**.

---

## 2. Diseño por capas

Cada recurso se organiza en tres capas con una sola responsabilidad cada una:

```
HTTP  ->  app/api/routes/     Router: rutas, parámetros, códigos de estado y modelo de respuesta
          app/services/       Servicio: reglas de negocio, consultas y commit
          app/models/         Modelos SQLAlchemy (tablas de T18)
          app/schemas/        Esquemas Pydantic de entrada y salida, uno por recurso
```

- Los **routers** no tienen lógica: reciben la petición y llaman a un servicio.
- Los **servicios** no importan FastAPI. Lanzan `ApiError`; un manejador global lo convierte en la respuesta JSON.
- Cada escritura termina con `confirmar()`: `flush`, `recalcular()` y `commit`.
- Todo acceso a datos filtra por el usuario del token. Un id ajeno responde **404**, igual que uno inexistente.

### Estructura de archivos

```
app/
  api/
    deps.py                 Alias Db y UsuarioActual para las firmas de los routers
    routes/
      tarjetas.py  deudas.py  msi.py  categorias.py  movimientos.py
  schemas/
    base.py                 Entrada, Edicion, Dinero, Tasa, Dia, EliminadoOut
    tarjeta.py  deuda.py  msi.py  movimiento.py  categoria.py
  services/
    comunes.py              obtener_del_usuario() y confirmar()
    tarjetas.py  deudas.py  msi.py  categorias.py  movimientos.py
    fechas.py               Próximas fechas de corte y pago, recurrentes del mes
    recalculo.py            Gancho de recálculo (vacío por ahora)
  models/                   usuario.py, finanzas.py, flujo.py, comunes.py
tests/
  conftest.py               SQLite en memoria, fixtures y fecha fija (2026-03-15)
  api/                      Pruebas de endpoints, un archivo por recurso
  unit/                     Pruebas de reglas y servicios sin HTTP
```

### Piezas compartidas

- **`obtener_del_usuario(db, modelo, id, usuario, error)`**: busca un registro propio o lanza el 404 que se le indique.
- **`confirmar(db, usuario)`**: cierre de toda escritura (`flush`, `recalcular`, `commit`).
- **`Entrada` / `Edicion`**: clases base de los esquemas. Ambas rechazan campos desconocidos (`usuario_id`, `cvv`, etc.) y recortan espacios. `Edicion` implementa el PUT parcial.
- **Tipos `Dinero`, `Tasa`, `Dia`**: dinero con máximo 2 decimales y 12 dígitos, tasa de 0 a 999.99, día de 1 a 31.

---

## 3. Convenciones de la API

| Código | Cuándo |
| --- | --- |
| 200 / 201 | Éxito / creado |
| 400 | Conflicto con el estado actual (`CATEGORIA_DUPLICADA`, `TARJETA_INACTIVA`) |
| 401 | Sin token o token inválido |
| 404 | No existe **o pertenece a otro usuario** |
| 422 | Datos con formato inválido o que incumplen una regla de validación (la lista completa está en la sección 6.6) |

Formato de error:

```json
{"codigo": "MONTO_INVALIDO", "mensaje": "El monto debe ser mayor a cero.",
 "campos": [{"campo": "monto", "mensaje": "Debe ser mayor a 0."}]}
```

Otras convenciones:

- **PUT parcial**: solo cambia lo que se envía. Se valida el estado final completo.
- Los montos salen como **número JSON**, no como texto.
- Los campos derivados **se calculan, no se guardan**: `mensualidades_restantes`, `saldo_pendiente`, `credito_disponible`, `porcentaje_limite_usado`, próximas fechas y el estatus de una deuda.
- Las fechas "de hoy" usan la hora de la Ciudad de México.

---

## 4. T29: tarjetas, deudas y planes MSI

### 4.1 Endpoints

| Método | Ruta | Éxito | Qué hace |
| --- | --- | --- | --- |
| GET | `/tarjetas?activa=` | 200 | Lista con saldo, % del límite usado, próxima fecha de corte y de pago |
| POST | `/tarjetas` | 201 | Registra una tarjeta |
| GET | `/tarjetas/{id}` | 200 | Detalle |
| PUT | `/tarjetas/{id}` | 200 | Edita (parcial) |
| DELETE | `/tarjetas/{id}` | 200 | Elimina la tarjeta y, en cascada, sus MSI y estados de cuenta |
| GET | `/msi?tarjeta_id=&estatus=` | 200 | Compras a MSI con mensualidades pagadas y restantes |
| POST | `/msi` | 201 | Registra un MSI ligado a una tarjeta |
| GET | `/msi/{id}` | 200 | Detalle |
| PUT | `/msi/{id}` | 200 | Edita (por ejemplo `mensualidades_pagadas`) |
| DELETE | `/msi/{id}` | 200 | Elimina |
| GET | `/deudas?estatus=` | 200 | Préstamos y créditos con saldo y próximo pago |
| POST | `/deudas` | 201 | Registra una deuda |
| GET | `/deudas/{id}` | 200 | Detalle |
| PUT | `/deudas/{id}` | 200 | Edita (parcial) |
| DELETE | `/deudas/{id}` | 200 | Elimina |

### 4.2 Validaciones

**Tarjeta**

- `nombre` y `banco`: 1 a 60 caracteres.
- `ultimos_4`: exactamente 4 dígitos (un número completo se rechaza).
- `limite_credito` ≥ 0 y `saldo_actual` ≥ 0 (por defecto 0).
- `dia_corte` y `dia_pago`: 1 a 31. `tasa_anual`: 0 a 999.99.

**Deuda**

- `monto_original` > 0 (`MONTO_INVALIDO`) y `saldo_actual` ≥ 0.
- `tipo` ∈ `prestamo_personal`, `credito_auto`, `credito_hipotecario`, `familiar_amigo`, `otro`.
- `pago_mensual` > 0 y `dia_pago` de 1 a 31.
- El `estatus` se **deriva del saldo**: saldo 0 ⇒ `liquidada`; subirlo la reactiva.

**Plan MSI** (T18 §4.1)

- La tarjeta debe ser propia y estar **activa** (`TARJETA_INACTIVA`).
- `categoria_id`, si se manda, es propia o del sistema.
- `num_mensualidades` ≥ 2 y no mayor al máximo configurado (60 por defecto, `MAX_MENSUALIDADES`).
- `mensualidades_pagadas` entre 0 y el total (`MSI_PAGADAS_EXCEDEN`).
- `monto_mensualidad × num_mensualidades = monto_original`, con tolerancia de 1 centavo por mensualidad (`MSI_MONTOS_INCOHERENTES`).
- `fecha_compra` no puede ser futura (`FECHA_INVALIDA`).

### 4.3 Reglas de cálculo

**Fechas de corte y pago de una tarjeta**

- Si hay un estado de cuenta con `fecha_limite_pago` ≥ hoy, esa fecha manda sobre `dia_pago` (T18 §4.3).
- Si no, se usa el siguiente `dia_pago`. Un día 31 en un mes corto cae en el **último día del mes**. El cambio de año se maneja.

**MSI**

- Si no se manda `monto_mensualidad`, se calcula `monto_original / num` redondeado a centavos. Al editar monto o meses se recalcula.
- `mensualidades_restantes = num_mensualidades − mensualidades_pagadas` y `saldo_pendiente = restantes × monto_mensualidad`.
- El estatus pasa a `liquidado` cuando `pagadas == total` y vuelve a `activo` si se baja el contador. `cancelado` lo pide el usuario.
- `origen` siempre queda `manual` desde la API.

**Eliminación en cascada**: borrar una tarjeta borra sus MSI y estados de cuenta, y la respuesta informa cuántos MSI se eliminaron.

### 4.4 Ejemplos

```bash
TOKEN="<JWT>"; API=http://localhost:8000/api/v1; H="Authorization: Bearer $TOKEN"
```

**Crear tarjeta**

```bash
curl -X POST $API/tarjetas -H "$H" -H "Content-Type: application/json" -d '{
  "nombre":"BBVA Azul","banco":"BBVA","ultimos_4":"1234",
  "limite_credito":20000,"saldo_actual":5000,"dia_corte":10,"dia_pago":30,"tasa_anual":45.5}'
```

```json
{"id":1,"nombre":"BBVA Azul","banco":"BBVA","ultimos_4":"1234","limite_credito":20000.0,
 "saldo_actual":5000.0,"credito_disponible":15000.0,"porcentaje_limite_usado":25.0,
 "dia_corte":10,"dia_pago":30,"tasa_anual":45.5,"activa":true,
 "proxima_fecha_corte":"2026-11-10","proxima_fecha_pago":"2026-10-30"}
```

**Actualizar saldo y día de pago**

```bash
curl -X PUT $API/tarjetas/1 -H "$H" -H "Content-Type: application/json" \
  -d '{"saldo_actual":10000,"dia_pago":28}'
```

**Registrar un MSI** (la mensualidad se calcula sola)

```bash
curl -X POST $API/msi -H "$H" -H "Content-Type: application/json" -d '{
  "tarjeta_id":1,"descripcion":"iPhone","monto_original":12000,
  "num_mensualidades":12,"mensualidades_pagadas":2,"fecha_compra":"2026-01-10"}'
```

```json
{"id":1,"tarjeta_id":1,"categoria_id":null,"descripcion":"iPhone","monto_original":12000.0,
 "num_mensualidades":12,"mensualidades_pagadas":2,"mensualidades_restantes":10,
 "monto_mensualidad":1000.0,"saldo_pendiente":10000.0,"fecha_compra":"2026-01-10",
 "estatus":"activo","origen":"manual"}
```

**Marcar una mensualidad más como pagada**

```bash
curl -X PUT $API/msi/1 -H "$H" -H "Content-Type: application/json" -d '{"mensualidades_pagadas":3}'
```

**Listar los MSI de una tarjeta**

```bash
curl "$API/msi?tarjeta_id=1" -H "$H"
```

**Registrar una deuda**

```bash
curl -X POST $API/deudas -H "$H" -H "Content-Type: application/json" -d '{
  "nombre":"Préstamo auto","acreedor":"Banorte","tipo":"credito_auto",
  "monto_original":150000,"saldo_actual":120000,"tasa_anual":14.9,
  "pago_mensual":4500,"dia_pago":5,"fecha_inicio":"2025-01-05"}'
```

**Liquidar una deuda** (queda con `"estatus":"liquidada"`)

```bash
curl -X PUT $API/deudas/1 -H "$H" -H "Content-Type: application/json" -d '{"saldo_actual":0}'
```

**Eliminar una tarjeta**

```bash
curl -X DELETE $API/tarjetas/1 -H "$H"
# {"id":1,"eliminado":true,"planes_msi_eliminados":1}
```

**Errores**

```json
// POST /msi con monto_mensualidad 900 (12 × 900 ≠ 12000) → 422
{"codigo":"MSI_MONTOS_INCOHERENTES","mensaje":"La mensualidad por el número de meses debe igualar el monto original (solo meses sin intereses; tolerancia de 1 centavo por mensualidad).","campos":[{"campo":"monto_mensualidad","mensaje":"No cuadra con monto_original y num_mensualidades."}]}

// POST /tarjetas con ultimos_4 "4111111111111111" → 422
{"codigo":"DATOS_INVALIDOS","mensaje":"Hay datos inválidos.","campos":[{"campo":"ultimos_4","mensaje":"Formato no válido."}]}

// POST /deudas con monto_original 0 → 422
{"codigo":"MONTO_INVALIDO","mensaje":"El monto debe ser mayor a cero.","campos":[{"campo":"monto_original","mensaje":"Debe ser mayor a 0."}]}
```

---

## 5. T27: ingresos, gastos y categorías

### 5.1 Endpoints

| Método | Ruta | Éxito | Qué hace |
| --- | --- | --- | --- |
| GET | `/movimientos?mes=AAAA-MM&tipo=&categoria_id=` | 200 | Lista del mes con totales; incluye los recurrentes que caen en ese mes |
| POST | `/movimientos` | 201 | Registra un ingreso o un gasto (fijo o variable) |
| PUT | `/movimientos/{id}` | 200 | Edita (parcial). El tipo ingreso/gasto no cambia |
| DELETE | `/movimientos/{id}` | 200 | Elimina |
| GET | `/categorias` | 200 | Categorías base y las propias |
| POST | `/categorias` | 201 | Crea una categoría propia |

T17 define una sola ruta para movimientos y T18 usa dos tablas (`ingreso` y `gasto`). Por eso el `id` lleva prefijo: `ingreso-5` o `gasto-12`.

### 5.2 Campos

| Campo de la API | Se guarda en | Notas |
| --- | --- | --- |
| `tipo` | Tabla `ingreso` o `gasto` | `ingreso` / `gasto` |
| `concepto` | `descripcion` | 1 a 120 caracteres |
| `monto` | `monto` | > 0, máximo 2 decimales |
| `frecuencia` | `frecuencia` | `unico`, `semanal`, `quincenal`, `mensual` |
| `fecha` | `fecha_inicio` | En `unico` es la fecha del movimiento |
| `fecha_fin` | `fecha_fin` | Opcional; no menor que `fecha` |
| `clase` | `gasto.tipo` | `fijo` / `variable`; solo gastos |
| `categoria_id` | `gasto.categoria_id` | Obligatoria en gastos; no aplica a ingresos |
| `activo` | `activo` | Por defecto `true`; los inactivos no salen en el mes |

### 5.3 Validaciones

- `monto` > 0 (`MONTO_INVALIDO`), máximo 2 decimales y 12 dígitos.
- `concepto` no vacío, máximo 120 caracteres. Los campos desconocidos dan 422.
- `fecha_fin` no puede ser menor que `fecha` (`FECHA_FIN_INVALIDA`).
- **Gasto**: `clase` obligatoria (`CLASE_REQUERIDA`) y `categoria_id` obligatoria (`CATEGORIA_REQUERIDA`).
- **Fijo vs. variable**: un gasto `variable` exige frecuencia `unico` (`VARIABLE_DEBE_SER_UNICO`); uno `fijo` exige cualquier otra (`FIJO_NO_PUEDE_SER_UNICO`).
- **Ingreso**: no admite `clase` ni `categoria_id` (`CAMPO_NO_APLICA`).
- Categoría ajena o inexistente: 404 `CATEGORIA_NO_ENCONTRADA`. Movimiento ajeno o inexistente: 404 `MOVIMIENTO_NO_ENCONTRADO`.
- `mes` con formato `AAAA-MM`; si falta, se usa el mes actual.
- **Categoría**: nombre de 1 a 60 caracteres, sin repetir (sin distinguir mayúsculas) entre las base y las propias: 400 `CATEGORIA_DUPLICADA`.
- Al editar se valida el estado final completo. Pasar un gasto de fijo a variable exige `frecuencia: "unico"` en el mismo PUT.

### 5.4 Recurrentes del mes

`GET /movimientos` expande cada movimiento recurrente a las fechas en que cae dentro del mes pedido, siempre entre `fecha` y `fecha_fin`:

- **`mensual`**: el día de `fecha`; si el mes es más corto, el último día.
- **`quincenal`**: dos veces al mes (el día de `fecha` ajustado a la primera quincena y 15 días después).
- **`semanal`**: cada 7 días contados desde `fecha`.
- **`unico`**: solo en su fecha.

Los totales del mes son `ingresos`, `gastos`, `gastos_fijos`, `gastos_variables` y `balance`.

### 5.5 Categorías base

Al crear las tablas se siembran 9 categorías base, comunes a todos los usuarios. Cada usuario puede agregar las suyas. `/categorias` solo tiene GET y POST, como define T17.

### 5.6 Ejemplos

**Categorías**

```bash
curl $API/categorias -H "$H"
curl -X POST $API/categorias -H "$H" -H "Content-Type: application/json" -d '{"nombre":"Mascotas"}'
# {"id":10,"nombre":"Mascotas","base":false}
```

**Ingreso quincenal**

```bash
curl -X POST $API/movimientos -H "$H" -H "Content-Type: application/json" -d '{
  "tipo":"ingreso","concepto":"Nómina","monto":15000,"frecuencia":"quincenal","fecha":"2026-10-01"}'
```

```json
{"id":"ingreso-1","tipo":"ingreso","concepto":"Nómina","monto":15000.0,"frecuencia":"quincenal",
 "fecha":"2026-10-01","fecha_fin":null,"activo":true,"categoria_id":null,"categoria":null,"clase":null}
```

**Gasto fijo**

```bash
curl -X POST $API/movimientos -H "$H" -H "Content-Type: application/json" -d '{
  "tipo":"gasto","clase":"fijo","concepto":"Renta","monto":8000,"frecuencia":"mensual",
  "fecha":"2026-10-05","categoria_id":1}'
```

**Gasto variable**

```bash
curl -X POST $API/movimientos -H "$H" -H "Content-Type: application/json" -d '{
  "tipo":"gasto","clase":"variable","concepto":"Cena","monto":500,"frecuencia":"unico",
  "fecha":"2026-10-15","categoria_id":2}'
```

**Lista del mes**

```bash
curl "$API/movimientos?mes=2026-10" -H "$H"
curl "$API/movimientos?mes=2026-10&tipo=gasto" -H "$H"
curl "$API/movimientos?mes=2026-10&categoria_id=1" -H "$H"
```

```json
{"mes":"2026-10",
 "totales":{"ingresos":30000.0,"gastos":8500.0,"gastos_fijos":8000.0,"gastos_variables":500.0,"balance":21500.0},
 "movimientos":[{"id":"ingreso-1","tipo":"ingreso","concepto":"Nómina","monto":15000.0,
                 "fecha_ocurrencia":"2026-10-01","clase":null,"categoria":null}]}
```

Cada movimiento trae además `frecuencia`, `fecha`, `fecha_fin`, `activo` y `categoria_id`.

**Editar y eliminar**

```bash
curl -X PUT $API/movimientos/gasto-1 -H "$H" -H "Content-Type: application/json" -d '{"monto":8500}'
curl -X DELETE $API/movimientos/gasto-2 -H "$H"      # {"id":"gasto-2","eliminado":true}
```

**Errores**

```json
// Gasto variable con frecuencia mensual → 422
{"codigo":"VARIABLE_DEBE_SER_UNICO","mensaje":"Un gasto variable debe tener frecuencia 'unico'.","campos":[{"campo":"frecuencia","mensaje":"Un gasto variable debe tener frecuencia 'unico'."}]}

// Monto 0 → 422
{"codigo":"MONTO_INVALIDO","mensaje":"El monto debe ser mayor a cero.","campos":[{"campo":"monto","mensaje":"Debe ser mayor a 0."}]}

// Categoría repetida → 400
{"codigo":"CATEGORIA_DUPLICADA","mensaje":"Ya existe una categoría con ese nombre.","campos":[{"campo":"nombre","mensaje":"Ya existe."}]}
```

---

## 6. Referencia completa de endpoints

Todos exigen `Authorization: Bearer <JWT>`. Sin token responden 401 `NO_AUTENTICADO`; con token inválido o vencido, 401 `TOKEN_INVALIDO`. Un id de otro usuario responde 404, igual que uno inexistente. Los `PUT` aceptan solo los campos que se envían, pero exigen al menos uno; los campos marcados "no admite null" no se pueden borrar con `null`.

### 6.1 Tarjetas

**`GET /tarjetas`**: parámetro opcional `activa` (`true` / `false`). Devuelve una lista de `TarjetaOut`.

**`POST /tarjetas`**: crea una tarjeta (201).

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `nombre` | texto | Sí | 1 a 60 caracteres |
| `banco` | texto | Sí | 1 a 60 caracteres |
| `ultimos_4` | texto | No | Exactamente 4 dígitos |
| `limite_credito` | dinero | Sí | ≥ 0 |
| `saldo_actual` | dinero | No (0.00) | ≥ 0 |
| `dia_corte` | entero | Sí | 1 a 31 |
| `dia_pago` | entero | Sí | 1 a 31 |
| `tasa_anual` | decimal | No | 0 a 999.99 |
| `activa` | booleano | No (`true`) | |

**`GET /tarjetas/{id}`**: devuelve un `TarjetaOut`. Si no existe o es ajena: 404 `TARJETA_NO_ENCONTRADA`.

**`PUT /tarjetas/{id}`**: mismos campos que al crear, todos opcionales. No admiten `null`: `nombre`, `banco`, `limite_credito`, `saldo_actual`, `dia_corte`, `dia_pago` y `activa`.

**`DELETE /tarjetas/{id}`**: devuelve `{"id", "eliminado": true, "planes_msi_eliminados": n}`.

**`TarjetaOut`** (respuesta): `id`, `nombre`, `banco`, `ultimos_4`, `limite_credito`, `saldo_actual`, `credito_disponible`, `porcentaje_limite_usado`, `dia_corte`, `dia_pago`, `tasa_anual`, `activa`, `proxima_fecha_corte`, `proxima_fecha_pago`.

### 6.2 Deudas

**`GET /deudas`**: parámetro opcional `estatus` (`activa` o `liquidada`). Devuelve una lista de `DeudaOut`.

**`POST /deudas`**: crea una deuda (201).

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `nombre` | texto | Sí | 1 a 100 caracteres |
| `acreedor` | texto | No | 1 a 100 caracteres |
| `tipo` | texto | Sí | `prestamo_personal`, `credito_auto`, `credito_hipotecario`, `familiar_amigo`, `otro` |
| `monto_original` | dinero | Sí | > 0 |
| `saldo_actual` | dinero | Sí | ≥ 0 |
| `tasa_anual` | decimal | No | 0 a 999.99 |
| `pago_mensual` | dinero | No | > 0 |
| `dia_pago` | entero | No | 1 a 31 |
| `fecha_inicio` | fecha | No | `AAAA-MM-DD` |

**`GET /deudas/{id}`**: devuelve un `DeudaOut`. Si no existe o es ajena: 404 `DEUDA_NO_ENCONTRADA`.

**`PUT /deudas/{id}`**: mismos campos, todos opcionales. No admiten `null`: `nombre`, `tipo`, `monto_original` y `saldo_actual`.

**`DELETE /deudas/{id}`**: devuelve `{"id", "eliminado": true}`.

**`DeudaOut`** (respuesta): `id`, `nombre`, `acreedor`, `tipo`, `monto_original`, `saldo_actual`, `tasa_anual`, `pago_mensual`, `dia_pago`, `fecha_inicio`, `estatus` (`activa` o `liquidada`, derivado del saldo), `proxima_fecha_pago`.

### 6.3 Planes MSI

**`GET /msi`**: parámetros opcionales `tarjeta_id` (≥ 1) y `estatus` (`activo`, `liquidado` o `cancelado`). Devuelve una lista de `MsiOut`.

**`POST /msi`**: crea un plan (201).

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `tarjeta_id` | entero | Sí | Tarjeta propia y activa |
| `categoria_id` | entero | No | Categoría base o propia |
| `descripcion` | texto | Sí | 1 a 120 caracteres |
| `monto_original` | dinero | Sí | > 0 |
| `num_mensualidades` | entero | Sí | De 2 al máximo configurado (60) |
| `mensualidades_pagadas` | entero | No (0) | De 0 a `num_mensualidades` |
| `monto_mensualidad` | dinero | No | > 0; si falta, se calcula |
| `fecha_compra` | fecha | Sí | No futura |

**`GET /msi/{id}`**: devuelve un `MsiOut`. Si no existe o es ajeno: 404 `MSI_NO_ENCONTRADO`.

**`PUT /msi/{id}`**: mismos campos, todos opcionales, más `estatus` (solo `activo` o `cancelado`; `liquidado` lo pone el servidor). No admiten `null`: `tarjeta_id`, `descripcion`, `monto_original`, `num_mensualidades`, `mensualidades_pagadas`, `monto_mensualidad`, `fecha_compra` y `estatus`.

**`DELETE /msi/{id}`**: devuelve `{"id", "eliminado": true}`.

**`MsiOut`** (respuesta): `id`, `tarjeta_id`, `categoria_id`, `descripcion`, `monto_original`, `num_mensualidades`, `mensualidades_pagadas`, `mensualidades_restantes`, `monto_mensualidad`, `saldo_pendiente`, `fecha_compra`, `estatus`, `origen`.

### 6.4 Movimientos (ingresos y gastos)

**`GET /movimientos`**: parámetros opcionales:

| Parámetro | Valores | Efecto |
| --- | --- | --- |
| `mes` | `AAAA-MM` (años 2000 a 2099) | Mes a consultar; por defecto, el actual |
| `tipo` | `ingreso` / `gasto` | Solo ese tipo |
| `categoria_id` | entero ≥ 1 | Solo gastos de esa categoría |

Devuelve `{"mes", "totales", "movimientos"}`. `totales` trae `ingresos`, `gastos`, `gastos_fijos`, `gastos_variables` y `balance`. Cada movimiento es un `MovimientoOut` más `fecha_ocurrencia`.

**`POST /movimientos`**: crea un movimiento (201).

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `tipo` | texto | Sí | `ingreso` o `gasto` |
| `concepto` | texto | Sí | 1 a 120 caracteres |
| `monto` | dinero | Sí | > 0 |
| `frecuencia` | texto | No (`unico`) | `unico`, `semanal`, `quincenal`, `mensual` |
| `fecha` | fecha | Sí | Inicio, o fecha del movimiento si es `unico` |
| `fecha_fin` | fecha | No | No menor que `fecha` |
| `clase` | texto | Solo gastos | `fijo` o `variable`; prohibida en ingresos |
| `categoria_id` | entero | Solo gastos | Prohibida en ingresos |
| `activo` | booleano | No (`true`) | |

**`PUT /movimientos/{id}`**: `id` con prefijo (`ingreso-5`, `gasto-12`). Campos opcionales: `concepto`, `monto`, `frecuencia`, `fecha`, `fecha_fin`, `categoria_id`, `clase`, `activo`. No se puede cambiar `tipo`. No admiten `null`: `concepto`, `monto`, `frecuencia`, `fecha` y `activo`.

**`DELETE /movimientos/{id}`**: devuelve `{"id": "gasto-12", "eliminado": true}`.

**`MovimientoOut`** (respuesta): `id`, `tipo`, `concepto`, `monto`, `frecuencia`, `fecha`, `fecha_fin`, `activo`, `categoria_id`, `categoria` (nombre), `clase`.

### 6.5 Categorías

**`GET /categorias`**: lista las categorías base y las propias. Cada una trae `id`, `nombre` y `base`.

**`POST /categorias`**: campo único `nombre` (1 a 60 caracteres, obligatorio). Devuelve la categoría creada (201).

### 6.6 Códigos de error

| Código | HTTP | Cuándo |
| --- | --- | --- |
| `NO_AUTENTICADO` / `TOKEN_INVALIDO` | 401 | Falta el token o no es válido |
| `DATOS_INVALIDOS` | 422 | Formato, tipo o campo desconocido incorrecto |
| `MONTO_INVALIDO` | 422 | Monto en cero o negativo |
| `TARJETA_NO_ENCONTRADA` | 404 | Tarjeta inexistente o ajena |
| `DEUDA_NO_ENCONTRADA` | 404 | Deuda inexistente o ajena |
| `MSI_NO_ENCONTRADO` | 404 | Plan inexistente o ajeno |
| `MOVIMIENTO_NO_ENCONTRADO` | 404 | Movimiento inexistente o ajeno, o id mal formado |
| `CATEGORIA_NO_ENCONTRADA` | 404 | Categoría inexistente o ajena |
| `TARJETA_INACTIVA` | 400 | MSI sobre una tarjeta inactiva |
| `CATEGORIA_DUPLICADA` | 400 | Nombre de categoría repetido |
| `MSI_MONTOS_INCOHERENTES` | 422 | La mensualidad por los meses no iguala el monto |
| `MSI_PAGADAS_EXCEDEN` | 422 | Más mensualidades pagadas que el total |
| `FECHA_INVALIDA` | 422 | Fecha de compra futura |
| `FECHA_FIN_INVALIDA` | 422 | `fecha_fin` anterior a `fecha` |
| `CLASE_REQUERIDA` / `CATEGORIA_REQUERIDA` | 422 | Gasto sin clase o sin categoría |
| `VARIABLE_DEBE_SER_UNICO` / `FIJO_NO_PUEDE_SER_UNICO` | 422 | Clase y frecuencia incompatibles |
| `CAMPO_NO_APLICA` | 422 | Ingreso con `clase` o `categoria_id` |

---

## 7. Pruebas

Se corren con SQLite en memoria y no necesitan MySQL:

```bash
docker compose exec api pytest -v
```

**136 pruebas** en total:

| Carpeta | Pruebas | Qué cubre |
| --- | --- | --- |
| `tests/api/` | 108 | Endpoints de punta a punta: autenticación (401), aislamiento entre usuarios (404 en GET, PUT y DELETE), todas las validaciones de este documento, filtros y errores |
| `tests/unit/` | 28 | Reglas puras y servicios sin HTTP: fechas recurrentes, validación de movimientos y de MSI, cálculos y consultas de los servicios |

Casos de fechas probados: día 31 en meses cortos, cambio de año, estado de cuenta que manda sobre `dia_pago`, y recurrentes semanales, quincenales y mensuales dentro de `fecha` … `fecha_fin`. También se prueban las transiciones `activo ⇄ liquidado ⇄ cancelado` y el borrado en cascada tarjeta → MSI.

---

## 8. Cómo levantarlo

```bash
docker compose up --build -d
docker compose exec api python -m app.crear_tablas   # crea las tablas y siembra las categorías base (idempotente)
docker compose exec api pytest -v
```

`.env` no se versiona: cada persona crea el suyo con las variables de MySQL (`MYSQL_PORT` incluido) y `JWT_SECRET`.

---

## 9. Decisiones y supuestos

1. **Id con prefijo** (`ingreso-5` / `gasto-12`): T17 tiene una sola ruta de movimientos y T18 dos tablas.
2. **Quincenal** significa dos veces al mes: el día de `fecha` y 15 días después.
3. **Gastos de tarjeta**: la tabla `gasto` es para efectivo, débito, renta, servicios, etc. Las compras con tarjeta entran por el estado de cuenta (T18) para no contarlas dos veces.
4. **`/categorias`** solo tiene GET y POST. No hay editar ni borrar; si se agrega, borrar una categoría con gastos queda bloqueado (`RESTRICT`).
5. **`anual`** existe en T18 pero no en T17; la API todavía no lo acepta.
6. **PUT parcial**: T17 lo ejemplifica con "mensualidades pagadas". Si el front manda siempre el objeto completo, funciona igual.
7. **Supuestos no definidos en T18**:
   - `saldo_actual` de una tarjeta es ≥ 0 (no se admite saldo a favor).
   - Máximo de 60 mensualidades (`MAX_MENSUALIDADES`).
   - No se exige `saldo ≤ monto_original` en deudas, porque los intereses pueden superarlo.
   - Un MSI cancelado conserva el cálculo de restantes y saldo; el front usa `estatus` para ignorarlo.

## 10. Pendientes

1. **`/auth`** no forma parte de estas tareas: `app/core/seguridad.py` solo valida el JWT con el mismo `JWT_SECRET`.
2. **`recalcular()`** (`app/services/recalculo.py`) es un gancho vacío. T17 pide recalcular score, historial y alertas en cada alta, cambio o baja; ya se invoca antes de cada commit.
3. **Contador vs. movimientos**: T18 sugiere comprobar que `mensualidades_pagadas` coincida con los movimientos ligados a `plan_msi_id`. Se hará cuando exista el módulo de estados de cuenta; por ahora el usuario edita el contador a mano.
4. **Frecuencia `anual`** para ingresos y gastos, si el equipo decide agregarla.
