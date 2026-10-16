# Endpoints de Tarjetas, Deudas y Planes MSI (T17 §4.3 + T18)

Todo vive bajo `/api/v1` (T17). Swagger: `http://localhost:8000/docs`.

## Cómo se prueba
```sh
docker compose up --build -d
docker compose exec api python -m app.crear_tablas     # crea las tablas (idempotente)
docker compose exec api pytest -v                      # pruebas (SQLite en memoria)
```

## Endpoints

| Método | Ruta | Éxito | Qué hace |
|---|---|---|---|
| GET | `/tarjetas?activa=` | 200 | Lista con saldo, % del límite usado, próxima fecha de corte y de pago |
| POST | `/tarjetas` | 201 | Registra tarjeta |
| GET | `/tarjetas/{id}` | 200 | Detalle *(extra al contrato)* |
| PUT | `/tarjetas/{id}` | 200 | Edita (parcial) |
| DELETE | `/tarjetas/{id}` | 200 | Elimina la tarjeta y, en cascada, sus MSI y estados de cuenta |
| GET | `/msi?tarjeta_id=&estatus=` | 200 | Compras a MSI con pagadas y restantes |
| POST | `/msi` | 201 | Registra MSI ligado a una tarjeta |
| GET | `/msi/{id}` | 200 | Detalle *(extra)* |
| PUT | `/msi/{id}` | 200 | Edita (p. ej. `mensualidades_pagadas`) |
| DELETE | `/msi/{id}` | 200 | Elimina |
| GET | `/deudas?estatus=` | 200 | Préstamos y créditos con saldo y próximo pago |
| POST | `/deudas` | 201 | Registra deuda |
| GET | `/deudas/{id}` | 200 | Detalle *(extra)* |
| PUT | `/deudas/{id}` | 200 | Edita (parcial) |
| DELETE | `/deudas/{id}` | 200 | Elimina |

Errores: 401 sin token/token inválido · 404 no existe **o es de otro usuario** · 422 datos inválidos · 400 regla de negocio.

## Validaciones del servidor

**Tarjeta** — `nombre`/`banco` 1–60 caracteres · `ultimos_4` exactamente 4 dígitos (un número completo se rechaza) ·
`limite_credito` ≥ 0 · `saldo_actual` ≥ 0 (default 0) · `dia_corte` y `dia_pago` 1–31 · `tasa_anual` 0–999.99 ·
dinero con máximo 2 decimales y 12 dígitos · campos desconocidos (`usuario_id`, `cvv`…) → 422.

**Deuda** — `monto_original` > 0 · `saldo_actual` ≥ 0 · `tipo` ∈ {prestamo_personal, credito_auto, credito_hipotecario, familiar_amigo, otro} ·
`pago_mensual` > 0 · `dia_pago` 1–31. El `estatus` se **deriva**: saldo 0 ⇒ `liquidada`; subirlo la reactiva.

**MSI** (T18 §4.1) — tarjeta propia y **activa** (si no: 404 / 400 `TARJETA_INACTIVA`) · `categoria_id` propia o del sistema ·
`num_mensualidades` ≥ 2 · `mensualidades_pagadas` entre 0 y el total (`MSI_PAGADAS_EXCEDEN`) ·
`monto_mensualidad × num_mensualidades = monto_original` con tolerancia de 1 centavo por mensualidad (`MSI_MONTOS_INCOHERENTES`) ·
`fecha_compra` no futura (`FECHA_INVALIDA`).
Si no se manda `monto_mensualidad`, se calcula `monto_original / num` a centavos; al editar monto o meses se recalcula.
`liquidado` lo pone el servidor cuando `pagadas == total` (y vuelve a `activo` si se baja el contador); `cancelado` lo pide el usuario.
`mensualidades_restantes` y `saldo_pendiente` **se calculan, no se guardan**. `origen` siempre queda `manual` desde la API.

**Próxima fecha de pago de una tarjeta** — si hay un estado de cuenta con `fecha_limite_pago` ≥ hoy, manda ese (T18 §4.3);
si no, el siguiente `dia_pago` (día 31 en meses cortos ⇒ último día del mes). Hora de México.

## Ejemplos (curl)

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

**Actualizar saldo y día de pago** → `curl -X PUT $API/tarjetas/1 -H "$H" -H "Content-Type: application/json" -d '{"saldo_actual":10000,"dia_pago":28}'`

**Registrar MSI** (mensualidad calculada)
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

**Marcar una mensualidad más como pagada** → `curl -X PUT $API/msi/1 -H "$H" -H "Content-Type: application/json" -d '{"mensualidades_pagadas":3}'`
**Listar MSI de una tarjeta** → `curl "$API/msi?tarjeta_id=1" -H "$H"`

**Registrar deuda**
```bash
curl -X POST $API/deudas -H "$H" -H "Content-Type: application/json" -d '{
  "nombre":"Préstamo auto","acreedor":"Banorte","tipo":"credito_auto",
  "monto_original":150000,"saldo_actual":120000,"tasa_anual":14.9,
  "pago_mensual":4500,"dia_pago":5,"fecha_inicio":"2025-01-05"}'
```
**Liquidar** → `curl -X PUT $API/deudas/1 -H "$H" -H "Content-Type: application/json" -d '{"saldo_actual":0}'` (queda `"estatus":"liquidada"`)

**Eliminar** → `curl -X DELETE $API/tarjetas/1 -H "$H"` → `{"id":1,"eliminado":true,"planes_msi_eliminados":1}`

**Errores**
```json
// POST /msi con monto_mensualidad 900 (12 × 900 ≠ 12000)  → 422
{"codigo":"MSI_MONTOS_INCOHERENTES","mensaje":"La mensualidad por el número de meses debe igualar el monto original (solo meses sin intereses; tolerancia de 1 centavo por mensualidad).","campos":[{"campo":"monto_mensualidad","mensaje":"No cuadra con monto_original y num_mensualidades."}]}
// POST /tarjetas con ultimos_4 "4111111111111111" → 422
{"codigo":"DATOS_INVALIDOS","mensaje":"Hay datos inválidos.","campos":[{"campo":"ultimos_4","mensaje":"Formato no válido."}]}
// POST /deudas con monto_original 0 → 422
{"codigo":"MONTO_INVALIDO","mensaje":"El monto debe ser mayor a cero.","campos":[{"campo":"monto_original","mensaje":"Debe ser mayor a 0."}]}
```

## Qué cubren las pruebas (`tests/`)
Autenticación (401), aislamiento entre usuarios (404 en GET/PUT/DELETE), todas las validaciones de arriba, fechas de corte/pago
(día 31, cambio de año, estado de cuenta que manda sobre la regla), cálculo y coherencia de MSI, transición `activo ⇄ liquidado ⇄ cancelado`
y borrado en cascada tarjeta → MSI.

## Pendientes
1. **`/auth` no está aquí** (otra tarea): `app/core/seguridad.py` solo valida el JWT (`sub` = id de usuario) con el mismo `JWT_SECRET`.
2. **`recalcular()`** (`app/services/recalculo.py`) es un gancho vacío: T17 pide recalcular score/historial/alertas en cada alta, cambio o baja; ya se llama antes del commit.
3. **PUT es parcial** (solo cambia lo enviado), porque T17 lo ejemplifica con "mensualidades pagadas". Si el front manda siempre el objeto completo, funciona igual.
4. **Supuestos no definidos en T18:** `saldo_actual` de tarjeta ≥ 0 (no se admite saldo a favor); máximo 60 mensualidades (`MAX_MENSUALIDADES`);
   no se exige `saldo ≤ monto_original` en deudas (los intereses pueden superarlo); un MSI cancelado conserva el cálculo de restantes/saldo (usar `estatus` para ignorarlo).
5. **Contador vs. movimientos:** T18 sugiere comprobar que `mensualidades_pagadas` coincida con los `movimiento.plan_msi_id` ligados. Se hará cuando exista el módulo de estados de cuenta; aquí el usuario puede editar el contador a mano.
6. Los montos salen como **número JSON** (no texto) para que el front los use directo.
