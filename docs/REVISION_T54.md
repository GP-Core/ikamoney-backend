# Revisión T54 · backend

Revisión con lista de verificación, no auditoría. Es la parte del **backend**; la caché de la PWA, IndexedDB y los formularios en pantalla son del frontend y no entran aquí. Rama `dev-gp-pruebas`.

La revisión quedó como **pruebas repetibles** en `tests/api/test_revision_t54.py` (unas 1,000 comprobaciones), así que cubre sola los endpoints que se agreguen después. Según el alcance de T54, los hallazgos se reportan a quien escribió cada parte; aquí no se arregló código ajeno.

## Qué se revisó y cómo salió

| Revisión | Resultado |
|---|---|
| **Autenticación**: toda ruta de `/api/v1` (32 combinaciones método + ruta) sin token y con token basura | ✅ 401 `NO_AUTENTICADO` / `TOKEN_INVALIDO` en todas. El token de recuperación de contraseña, uno firmado con otra llave y uno sin firma tampoco sirven como sesión |
| **Aislamiento entre usuarios**: dos usuarios, un recurso de cada tipo (tarjeta, MSI, deuda, categoría, ingreso, gasto, alerta) | ✅ El otro usuario recibe 404 en `GET`, `PUT`, `DELETE` y `PATCH` (misma respuesta que un id inexistente), los listados le salen vacíos, no puede colgar un MSI de mi tarjeta ni un gasto de mi categoría, y el cuerpo no puede cambiar el dueño (`usuario_id` → 422) |
| **Validación del servidor**: 7 recursos × cada campo × 27 valores basura (negativos, cero, `NaN`, `Infinity`, `1e308`, `1e400`, 23 dígitos, tres decimales, 10,000 caracteres, fechas imposibles, `null`, tipos equivocados, inyección SQL, HTML, `\u0000`, emoji) | ✅ **Cero respuestas 500** y todos los errores con el formato `{codigo, mensaje, campos}`. Además 40 casos que *deben* rechazarse (saldos negativos, monto 0, `ultimos_4` corto, día 32, contraseña débil…) se rechazan |
| **Errores sin detalles internos**: excepción interna, error de base de datos, 404, 405, JSON roto, ids y parámetros raros | ✅ El 500 es siempre `{"codigo":"ERROR_INTERNO","mensaje":"Ocurrió un error inesperado."}`: sin trazas, SQL ni nombres de tablas |
| **Borrado del PDF** (T53a) | ✅ Ver `docs/ESTADOS_CUENTA.md` |

## Hallazgos

Gravedad: **Alta** = arreglar antes de la demo o de abrir la app a usuarios reales; **Media** = sprint 10; **Baja** = si hay tiempo.

| # | Gravedad | Hallazgo | Dónde | Responsable | Estado |
|---|---|---|---|---|---|
| H-01 | Alta | **`JWT_SECRET` tiene un valor por defecto público** (`cambia_esto_en_produccion`) y la API arranca igual con él: quien conozca el repositorio puede firmar tokens de cualquier usuario. El `.env` actual no define `JWT_SECRET` (hallazgo B0.4 del plan) | `app/core/config.py` | Quien hizo la configuración / T58 | Abierto. Arreglo: negarse a arrancar con ese valor cuando no se está en pruebas |
| H-02 | Media | **El login no limita intentos**: se puede probar contraseñas sin freno. Argon2 lo hace lento (decenas de ms) pero no lo detiene. `docs/ELIMINAR_CUENTA.md` ya lo anota como pendiente | `POST /api/auth/login`, `DELETE /api/v1/cuenta` | T51 | Abierto → sprint 10 |
| H-03 | Media | **`/docs`, `/redoc` y `/openapi.json` son públicos** y listan todos los endpoints y esquemas, también en producción | `app/main.py` | T17 / T58 | Abierto. Arreglo: `docs_url=None` salvo en desarrollo |
| H-04 | Media | **`/estados-cuenta/extraer` no tiene límite de frecuencia**: cada llamada gasta cuota de Gemini (costo) y hasta 30 s de un worker. Un usuario, o un token robado, puede agotarla | `POST /api/v1/estados-cuenta/extraer` | T31 | Abierto → sprint 10 |
| H-05 | Baja | **Los ids de la URL no tienen tope**: `GET /api/v1/tarjetas/99999999999999999999999` da 500 con SQLite (`OverflowError`). Con MySQL probablemente responde 404 (**sin verificar**). Lo mismo en deudas y MSI. Las alertas ya lo acotan (`Path(ge=1, le=2**63-1)`) | `routes/tarjetas.py`, `deudas.py`, `msi.py` | T29 | Abierto. Pruebas `test_h05_*` marcadas `xfail`: pasan a verde cuando se arregle |
| H-06 | Baja | **`/api/ping-db` es público y su 404 nombra la tabla** (`La tabla pipeline_check está vacía`). Es una prueba de la tubería, no necesita estar en producción | `routes/health.py` | T19 | Abierto |
| H-07 | Baja | **Sin cabeceras de seguridad** (`Strict-Transport-Security`, `X-Content-Type-Options`, `Cache-Control: no-store` en las respuestas con datos financieros). Caddy puede ponerlas | `Caddyfile` | T58 | Abierto |
| H-08 | Info | **El token no se puede revocar**: `logout` responde 204 sin hacer nada y un token robado sirve 24 h. Es una decisión documentada (B1); se anota por el aviso de privacidad | `services/auth.py` | T51 | Aceptado, a documentar en T55 |
| H-09 | Info | Una subida **sin** `Content-Length` (transferencia fragmentada) no la corta el middleware de 11 MB y Starlette puede dejarla en un temporal. El navegador siempre manda `Content-Length` | `app/main.py` | T31 / T53 | Documentado en `docs/ESTADOS_CUENTA.md` |

## No revisado (queda para el sprint 10)

- Todo lo del frontend: formularios en pantalla, caché del service worker, IndexedDB y datos que sobreviven al cierre de sesión. **Es lo más conviene revisar**: entre T59, T60 y T56 tres personas tocaron lo que se guarda en el dispositivo.
- Comportamiento propio de MySQL: las pruebas corren en SQLite (H-05, los `CHECK`, la concurrencia del `UNIQUE` de las alertas).
- CORS: se comprobó que un origen desconocido no recibe `Access-Control-Allow-Origin`; no se revisó la lista real de producción.
- Prueba de carga y de recursos (tamaño de la proyección a 24 meses con muchos movimientos).

## Cómo repetirla

```sh
docker compose exec api pytest tests/api/test_revision_t54.py -q
```
