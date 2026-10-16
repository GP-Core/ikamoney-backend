# Endpoints de ingresos, gastos y categorías (T17 §4.2 + T18 §5)

Todo bajo `/api/v1`, con JWT `Bearer` y errores `{codigo, mensaje, campos}`. Swagger: `http://localhost:8000/docs`.

## Cómo se prueba
```sh
docker compose up --build -d
docker compose exec api python -m app.crear_tablas   # crea ingreso y gasto y siembra las categorías base
docker compose exec api pytest -v
```

## Endpoints

| Método | Ruta | Éxito | Qué hace |
|---|---|---|---|
| GET | `/movimientos?mes=AAAA-MM&tipo=&categoria_id=` | 200 | Lista del mes con totales; incluye los recurrentes que caen en ese mes |
| POST | `/movimientos` | 201 | Registra un ingreso o un gasto (fijo o variable) |
| PUT | `/movimientos/{id}` | 200 | Edita (parcial). El tipo ingreso/gasto no cambia |
| DELETE | `/movimientos/{id}` | 200 | Elimina |
| GET | `/categorias` | 200 | Categorías base y las propias |
| POST | `/categorias` | 201 | Crea una categoría propia |

El `id` de un movimiento lleva prefijo: `ingreso-5` o `gasto-12` (son dos tablas en T18).

## Campos

| Campo API | Se guarda en | Notas |
|---|---|---|
| `tipo` | tabla `ingreso` o `gasto` | `ingreso` / `gasto` |
| `concepto` | `descripcion` | 1–120 caracteres |
| `monto` | `monto` | > 0, máximo 2 decimales |
| `frecuencia` | `frecuencia` | `unico`, `semanal`, `quincenal`, `mensual` (T17); T18 también admite `anual`, la API aún no lo acepta |
| `fecha` | `fecha_inicio` | En `unico` es la fecha del movimiento |
| `fecha_fin` | `fecha_fin` | Opcional; no menor que `fecha` |
| `clase` | `gasto.tipo` | `fijo` / `variable`; solo gastos |
| `categoria_id` | `gasto.categoria_id` | Obligatoria en gastos; no aplica a ingresos |
| `activo` | `activo` | Por defecto `true`; los inactivos no salen en el mes |

## Validaciones del servidor
- `monto` > 0 (`MONTO_INVALIDO`), máximo 2 decimales, hasta 12 dígitos.
- `concepto` no vacío, máximo 120. Campos desconocidos (`usuario_id`, etc.) → 422.
- `fecha_fin` no menor que `fecha` (`FECHA_FIN_INVALIDA`).
- Gasto: `categoria_id` obligatoria (`CATEGORIA_REQUERIDA`) y `clase` obligatoria (`CLASE_REQUERIDA`).
- Gasto `variable` ⇒ frecuencia `unico` (`VARIABLE_DEBE_SER_UNICO`); gasto `fijo` ⇒ cualquier otra (`FIJO_NO_PUEDE_SER_UNICO`).
- Ingreso sin `clase` ni `categoria_id` (`CAMPO_NO_APLICA`).
- Categoría base o propia; de otro usuario o inexistente → 404 `CATEGORIA_NO_ENCONTRADA`.
- Movimiento inexistente o de otro usuario → 404 `MOVIMIENTO_NO_ENCONTRADO`.
- `mes` con formato `AAAA-MM` (si no, 422). Sin `mes` se usa el mes actual (hora de México).
- Categoría: nombre 1–60, sin repetir (sin distinguir mayúsculas) entre las base y las propias → 400 `CATEGORIA_DUPLICADA`.
- Al editar se valida el estado final completo (p. ej. pasar un gasto de fijo a variable exige `frecuencia: unico` en el mismo PUT).

## Cálculo de recurrentes del mes
- `mensual`: el día de `fecha`; si el mes es más corto, el último día.
- `quincenal`: dos veces al mes (el día de `fecha` ajustado a la 1.ª quincena y 15 días después).
- `semanal`: cada 7 días contados desde `fecha`.
- Siempre dentro de `fecha` … `fecha_fin`.

## Ejemplos (curl)
```bash
TOKEN="<JWT>"; API=http://localhost:8000/api/v1; H="Authorization: Bearer $TOKEN"
```

**Categorías**
```bash
curl $API/categorias -H "$H"
curl -X POST $API/categorias -H "$H" -H "Content-Type: application/json" -d '{"nombre":"Mascotas"}'
```
```json
{"id":10,"nombre":"Mascotas","base":false}
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
(Cada movimiento trae además `frecuencia`, `fecha`, `fecha_fin`, `activo` y `categoria_id`.)

**Editar / eliminar**
```bash
curl -X PUT $API/movimientos/gasto-1 -H "$H" -H "Content-Type: application/json" -d '{"monto":8500}'
curl -X DELETE $API/movimientos/gasto-2 -H "$H"      # {"id":"gasto-2","eliminado":true}
```

**Errores**
```json
// gasto variable con frecuencia mensual → 422
{"codigo":"VARIABLE_DEBE_SER_UNICO","mensaje":"Un gasto variable debe tener frecuencia 'unico'.","campos":[{"campo":"frecuencia","mensaje":"Un gasto variable debe tener frecuencia 'unico'."}]}
// monto 0 → 422
{"codigo":"MONTO_INVALIDO","mensaje":"El monto debe ser mayor a cero.","campos":[{"campo":"monto","mensaje":"Debe ser mayor a 0."}]}
// categoría repetida → 400
{"codigo":"CATEGORIA_DUPLICADA","mensaje":"Ya existe una categoría con ese nombre.","campos":[{"campo":"nombre","mensaje":"Ya existe."}]}
```

## Decisiones a confirmar con el equipo
1. **Id con prefijo** (`ingreso-5` / `gasto-12`), porque T17 tiene una sola ruta y T18 dos tablas.
2. **Quincenal** = dos veces al mes (día de `fecha` y +15 días).
3. **Gastos de tarjeta**: la tabla `gasto` es solo para efectivo, débito, renta, servicios, etc. Las compras con tarjeta entran por el estado de cuenta (T18) para no contarlas dos veces.
4. **`/categorias`** solo tiene GET y POST (T17). No hay editar ni borrar; si se agrega, borrar una categoría con gastos está bloqueado (RESTRICT).
5. **`anual`** existe en T18 pero no en T17; la API aún no lo acepta.
6. `recalcular()` (score, historial, alertas) sigue siendo un gancho vacío; ya se llama en cada alta, cambio y baja.
