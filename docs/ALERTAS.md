# Alertas · T47 (contrato para T48, T49 y T50)

Motor de reglas, centro de notificaciones, configuración y revisión diaria. Todo bajo `/api/v1/alertas`, con el token del usuario, salvo la ruta del cron (`/api/internos/...`, con llave secreta).

> **Por confirmar contra T15.** El documento con las reglas AL-01 a AL-04 no está en el repositorio. Las cuatro de abajo salen de RF-64, RF-65, CE-10 y el semáforo de `09-investigacion-financiera.md`. Si T15 dice otra cosa, cambian `app/services/alertas_reglas.py` y `app/core/reglas_alertas.json`; los endpoints no.

## Reglas

| Regla | Se dispara cuando… | Severidad | Configurable |
|---|---|---|---|
| **AL-01** | En algún mes de los próximos 12, los compromisos (pagos de tarjetas, MSI y cuotas de deudas) superan los ingresos. Una sola alerta, con el primer mes. Sin ningún ingreso registrado no avisa | `critica` | No |
| **AL-02** | La utilización de una tarjeta, `(saldo + MSI pendiente) / límite`, llega al umbral y no pasa de 100 % | `atencion` | **Umbral**, 70 % por defecto |
| **AL-03** | Faltan 0 a N días para la fecha límite de pago de una tarjeta con saldo | `atencion` | **Días de anticipación**, 3 por defecto |
| **AL-04** | `saldo + MSI pendiente` supera el límite de la tarjeta (CE-10). **Sustituye** a AL-02: una tarjeta nunca tiene las dos a la vez | `critica` | No |

Los datos salen de los mismos motores que usa la app: la proyección (T33) y el pendiente de MSI de la Fórmula 4 (T25). Los textos **no llevan saldos ni montos** (IC-07): nombran la tarjeta, el mes o la fecha, y el umbral configurado.

## Cuándo se evalúa

- **Después de cada cambio del usuario:** `recalcular()` (el mismo gancho del score) llama a la revisión en la misma transacción.
- **Una vez al día:** `POST /api/internos/revision-diaria`. Es lo que hace aparecer AL-03 sin que el usuario toque nada.
- Al cambiar la configuración (`PUT /alertas/configuracion`).

## Cuándo se repite una alerta (y cuándo no)

| Situación | Qué pasa |
|---|---|
| La condición sigue cumpliéndose | **Nada.** Ni fila nueva ni aviso. Da igual que la alerta esté leída o no |
| La condición deja de cumplirse | La alerta pasa a `resuelta` (con `resuelta_en`) y deja de contar como pendiente |
| Vuelve a cumplirse **menos de 24 h** después de resolverse | Se reactiva **la misma fila**, sin volver a avisar (evita el correo repetido cuando el saldo oscila alrededor del umbral) |
| Vuelve a cumplirse **24 h o más** después | Alerta nueva, con aviso |
| AL-01 cambia de mes, o cambia el umbral de AL-02 | Se actualiza el texto de la misma alerta, sin aviso nuevo |
| AL-03 en el siguiente ciclo de pago | Alerta nueva: la fecha va en la referencia (`tarjeta:7:2026-04-30`) |
| Dos peticiones a la vez | La base lo impide: `UNIQUE (usuario_id, clave_activa)`; la segunda no inserta |

## Endpoints

### `GET /api/v1/alertas`

Query: `estado` = `activa` (por defecto), `resuelta` o `todas`; `limite` de 1 a 100 (50 por defecto). Más recientes primero.

```json
{
  "total": 2,
  "sin_leer": 1,
  "alertas": [
    {
      "id": 14,
      "regla": "AL-02",
      "severidad": "atencion",
      "titulo": "Utilización alta en BBVA Azul",
      "mensaje": "BBVA Azul usa 70 % o más de su límite de crédito.",
      "accion": "Paga parte del saldo o evita nuevas compras con esta tarjeta.",
      "referencia": "tarjeta:3",
      "estado": "activa",
      "leida": false,
      "creada_en": "2026-11-17T09:30:00",
      "resuelta_en": null
    }
  ]
}
```

- `total` es el número de alertas de esta respuesta. **`sin_leer` siempre cuenta las activas no leídas**, sin importar el filtro: es el número de la campana.
- `severidad`: `atencion` (amarillo) o `critica` (rojo). El texto sigue la estructura de la guía: `titulo` (qué pasa), `mensaje` (detalle) y `accion` (qué hacer).
- Fechas sin zona horaria, en hora de México.

### `PATCH /api/v1/alertas/{id}`

Cuerpo: `{ "leida": true }` (o `false` para devolverla a no leída). Responde la alerta con la misma forma de arriba.

| Estado | Código | Cuándo |
|---|---|---|
| 404 | `ALERTA_NO_ENCONTRADA` | El id no existe **o es de otro usuario** (misma respuesta) |
| 422 | `DATOS_INVALIDOS` | Falta `leida`, no es booleano o trae otro campo |

### `GET /api/v1/alertas/configuracion` · `PUT /api/v1/alertas/configuracion`

```json
{ "umbral_utilizacion": 70, "dias_anticipacion": 3, "canales": { "correo": true, "push": false } }
```

Sin configuración guardada, el `GET` devuelve estos valores por defecto. El `PUT` es parcial: solo cambia lo que se envía, y al menos un campo es obligatorio.

| Campo | Rango | Notas |
|---|---|---|
| `umbral_utilizacion` | entero de 10 a 100 | Porcentaje |
| `dias_anticipacion` | entero de 1 a 15 | Para AL-03 |
| `canales.correo` / `canales.push` | booleano | `canales` admite uno solo o los dos |

`null`, un objeto `canales` vacío, un canal desconocido o un campo ajeno dan 422 `DATOS_INVALIDOS` con `campos`. El `PUT` **reevalúa las alertas** con el valor nuevo antes de responder: tras cambiar el umbral, un `GET /alertas` ya refleja el cambio.

### `POST /api/internos/revision-diaria` (solo el cron)

Encabezado `X-Llave-Interna: <CRON_SECRET>`. No usa el token de un usuario. Cuerpo vacío.

```json
{ "usuarios_revisados": 12, "alertas_nuevas": 3, "alertas_resueltas": 1, "avisos_enviados": 3, "errores": 0 }
```

| Estado | Código | Cuándo |
|---|---|---|
| 200 | | Revisión hecha. Un usuario que falla se cuenta en `errores` y no detiene a los demás |
| 401 | `LLAVE_INVALIDA` | Falta el encabezado o la llave no coincide (se compara en tiempo constante) |
| 503 | `CRON_NO_CONFIGURADO` | El servidor no tiene `CRON_SECRET`: la ruta queda **cerrada** |

La respuesta no trae correos, nombres ni montos. Para T50: configurar `CRON_SECRET` en el servidor y el mismo valor como secreto del cron (`docs/NOTIFICACIONES.md`).

## Datos

| Tabla | Para qué |
|---|---|
| `alerta` | Una fila por alerta, activa o resuelta (queda como historial). `clave_activa` = `REGLA\|referencia` mientras está activa y `NULL` al resolverse; con el `UNIQUE` evita duplicados. `notificada_en` marca que ya se envió por correo o push |
| `alerta_configuracion` | Una fila por usuario, creada la primera vez que cambia algo |

Ambas tienen `ON DELETE CASCADE` hacia `usuario` y se borran en `services/cuenta.py`. Son tablas nuevas: en una base existente basta `docker compose exec api python -m app.crear_tablas`, no hace falta recrear el volumen.

## Pruebas

`tests/unit/test_alertas_reglas.py` (cada regla, en el borde) y `tests/api/test_alertas.py` (no duplicar, resolver, reactivar, enfriamiento, configuración, aislamiento entre usuarios, cron).
