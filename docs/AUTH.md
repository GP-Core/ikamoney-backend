# Acceso: `/api/auth` (T51)

Las rutas van bajo `/api/auth`, **no** bajo `/api/v1`: es lo que ya llama el frontend (`src/services/authApi.ts`). Errores con la forma de siempre, `{codigo, mensaje, campos}`. Código: `app/api/routes/auth.py`, `app/services/auth.py`, `app/schemas/auth.py`.

| Endpoint | Cuerpo | Respuesta |
|---|---|---|
| `POST /api/auth/registro` | `{nombre, correo, contrasena, acepta_terminos}` | 201 `{access_token, token_type, expira_en, usuario}` |
| `POST /api/auth/login` | `{correo, contrasena}` | 200, igual que registro |
| `GET /api/auth/me` | — (token) | 200 `{id, nombre, correo, moneda}` |
| `POST /api/auth/logout` | — | 204 |
| `POST /api/auth/recuperar-contrasena` | `{correo}` | 200 `{mensaje}` (+ `enlace_prueba`, ver abajo) |
| `POST /api/auth/restablecer-contrasena` | `{token, contrasena}` | 204 |

`expira_en` son segundos (`JWT_HORAS * 3600`).

## Reglas

- `nombre` de 2 a 100 caracteres. `contrasena` de 8 a 64, con una letra y un número (igual que `utils/validation.ts`). La contraseña no se recorta.
- `correo` se guarda en minúsculas y es único.
- Sin `acepta_terminos: true` no se crea la cuenta (RNF-20).
- Contraseña con Argon2id (`hash_contrasena`). El registro confirma con `db.commit()`, no con `confirmar()`, para no guardar un score de un usuario sin datos.

## Códigos de error

| Estado | Código | Cuándo |
|---|---|---|
| 401 | `NO_AUTENTICADO` / `TOKEN_INVALIDO` | Sin token, o token vencido, inválido o de recuperación |
| 401 | `CREDENCIALES_INVALIDAS` | Login fallido; **mismo cuerpo** exista o no el correo (REQ-CU-04) |
| 409 | `CORREO_YA_REGISTRADO` | Registro con un correo existente (también con otras mayúsculas) |
| 422 | `TERMINOS_NO_ACEPTADOS` | `acepta_terminos` falso |
| 422 | `DATOS_INVALIDOS` | Nombre, correo o contraseña fuera de las reglas |
| 400 | `ENLACE_INVALIDO` | Token de recuperación inválido, vencido, ya usado o de sesión |

## Recuperar contraseña

No hay servicio de correo (T50). `recuperar-contrasena` responde siempre el mismo mensaje. Con `RECUPERACION_ENLACE_PRUEBA=true` (solo desarrollo) y un correo registrado, agrega `enlace_prueba` = `{FRONTEND_URL}/restablecer-contrasena?token=...`; en producción debe estar en `false`.

El token es un JWT de `RECUPERACION_MINUTOS` (30) con `uso: "recuperacion"` y una `huella` del hash de contraseña vigente. Al cambiar la contraseña la huella deja de coincidir, así que el enlace sirve una sola vez sin tabla. `usuario_actual` rechaza cualquier token con `uso`.

## Limitaciones conocidas

- Los tokens no se revocan: `logout` no hace nada en el servidor, y cambiar la contraseña no cierra las sesiones abiertas.
- No hay límite de intentos de login (el frontend ya sabe mostrar el 429).
- `FRONTEND_URL` solo se usa para armar el enlace de prueba.
