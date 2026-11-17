# Eliminar cuenta y datos · T56

El usuario elimina su cuenta y se borra todo lo suyo: en el servidor con `DELETE /api/v1/cuenta` y en su dispositivo desde el frontend. Es irreversible.

## Contrato

```
DELETE /api/v1/cuenta
Authorization: Bearer <token>
Content-Type: application/json

{ "contrasena": "la contraseña actual" }
```

| Respuesta | Código | Qué pasó |
|---|---|---|
| `204` sin cuerpo | | La cuenta y todos sus datos se borraron. El token deja de servir |
| `401` | `NO_AUTENTICADO` / `TOKEN_INVALIDO` | Falta el token o ya no es válido |
| `403` | `CONTRASENA_INCORRECTA` | La contraseña no coincide. **No se borra nada** |
| `422` | `DATOS_INVALIDOS` | Falta `contrasena`, va vacía o se mandó un campo que no existe |

- La contraseña incorrecta responde **403 y no 401**: para el frontend un 401 significa "la sesión ya no sirve" y cerraría la sesión.
- La contraseña se compara tal cual, sin recortar espacios (`CuentaEliminar` desactiva el recorte de `Entrada`).
- No hay límite de intentos todavía; queda para el módulo `/auth` (T51).

## Contraseñas

`app/core/seguridad.py` tiene las dos funciones que usa este endpoint y que debe reutilizar `/auth` (T51):

- `hash_contrasena(texto)`: hash Argon2id (`argon2-cffi`) para guardar en `usuario.contrasena_hash`.
- `verificar_contrasena(texto, hash)`: `True` si coincide. Con un hash que no es Argon2 devuelve `False`.

Los usuarios creados a mano con `contrasena_hash="x"` o `"no-usar"` (README, `seed_demo.py`) **no pueden eliminar su cuenta** hasta tener un hash real. Para ponerle contraseña a uno:

```bash
docker compose exec api python -c "from sqlalchemy import select; from app.core.database import SessionLocal; from app.core.seguridad import hash_contrasena; from app.models import Usuario; db = SessionLocal(); u = db.scalar(select(Usuario).where(Usuario.correo == 'demo@ikamoney.dev')); u.contrasena_hash = hash_contrasena('CAMBIA-ESTA-CLAVE'); db.commit()"
```

## Qué se borra y en qué orden

`app/services/cuenta.py` borra en una sola transacción (si un paso falla, no se borra nada):

| Orden | Tabla | Por qué en ese lugar |
|---|---|---|
| 1 | `gasto` | `gasto.categoria_id` es `RESTRICT`: va antes que `categoria` (ver nota) |
| 2 | `ingreso` | |
| 3 | `movimiento` | Cuelga de `estado_cuenta` |
| 4 | `plan_msi` | Cuelga de `tarjeta` |
| 5 | `estado_cuenta` | Cuelga de `tarjeta` |
| 6 | `tarjeta` | |
| 7 | `deuda` | |
| 8 | `score_historial` | |
| 9 | `alerta` y `alerta_configuracion` | Alertas (T47) |
| 10 | `categoria` | Solo las propias; las 9 base (`usuario_id NULL`) se conservan |
| 11 | `usuario` | Su `ON DELETE CASCADE` arrastra las tablas sin modelo, como `resumen_mensual` |

No se usa `confirmar()`: su `recalcular()` guardaría un score nuevo del usuario que se está borrando.

**Nota sobre el orden.** No basta con borrar `usuario` y dejar todo al `ON DELETE CASCADE`. Probado en MySQL 8.0 con un usuario que tiene un gasto en una categoría propia:

```
DELETE FROM usuario WHERE id = 2;
ERROR 1451 (23000): Cannot delete or update a parent row: a foreign key constraint fails
(`gasto`, CONSTRAINT `fk_gasto_categoria_id_categoria` ... ON DELETE RESTRICT)
```

Las pruebas corren en SQLite y no detectan esto; por eso el borrado se verificó en MySQL.

### Tablas nuevas (alertas, simulaciones guardadas, suscripciones push)

`alerta` y `alerta_configuracion` ya están en la lista. Las demás (simulaciones guardadas, suscripciones push) todavía no existen. Cuando se agreguen:

1. Su llave hacia `usuario` (o hacia una tabla del usuario) debe ser `ON DELETE CASCADE`. `tests/api/test_cuenta.py::test_toda_llave_foranea_define_que_pasa_al_borrar` falla si no lo es.
2. Agrégala a los pasos de `app/services/cuenta.py` y a `_conteos()` en `tests/api/test_cuenta.py`.

## Verificación en MySQL (13-nov-2026)

Se hizo en una base MySQL 8.0 nueva, creada desde `db/schema.sql` (incluye `resumen_mensual`), con dos usuarios:

- **Usuario 1 (se elimina):** datos de `seed_demo.py --con-deuda`, más una categoría propia con un gasto, un estado de cuenta con un movimiento ligado a un plan MSI, historial de score y un resumen mensual.
- **Usuario 2 (testigo):** una fila o más en cada tabla. No debe perder nada.

| Paso | Respuesta | Resultado |
|---|---|---|
| Contraseña incorrecta | `403 CONTRASENA_INCORRECTA` | Conteos idénticos a los de antes; el token sigue sirviendo (200) |
| Contraseña correcta | `204` | Conteos de abajo; el mismo token responde `401` |

Filas por tabla, consultadas directo en MySQL:

| Tabla | Usuario 1 antes | Usuario 1 después | Testigo antes | Testigo después | Total después |
|---|---|---|---|---|---|
| `usuario` | 1 | 0 | 1 | 1 | 1 |
| `categoria` | 1 | 0 | 1 | 1 | 10 (9 base + 1 del testigo) |
| `ingreso` | 1 | 0 | 1 | 1 | 1 |
| `gasto` | 3 | 0 | 2 | 2 | 2 |
| `tarjeta` | 2 | 0 | 1 | 1 | 1 |
| `estado_cuenta` | 1 | 0 | 1 | 1 | 1 |
| `movimiento` | 1 | 0 | 1 | 1 | 1 |
| `plan_msi` | 2 | 0 | 1 | 1 | 1 |
| `deuda` | 1 | 0 | 1 | 1 | 1 |
| `score_historial` | 5 | 0 | 1 | 1 | 1 |
| `resumen_mensual` | 1 | 0 | 1 | 1 | 1 |

En todas las tablas el total después es exactamente lo del testigo (más las categorías base): no quedó ningún registro del usuario eliminado ni huérfano. La lista de tablas se cotejó con `information_schema.key_column_usage` para no omitir ninguna.

### Cómo repetirla

1. Con la API arriba, pon una contraseña real al usuario (comando de la sección **Contraseñas**) y anota su `id`.
2. Cuenta antes y después con esta consulta, cambiando `@u` por ese `id`:

```sql
SET @u := 1;
SELECT 'usuario' AS tabla, COUNT(*) AS filas FROM usuario WHERE id = @u
UNION ALL SELECT 'categoria', COUNT(*) FROM categoria WHERE usuario_id = @u
UNION ALL SELECT 'ingreso', COUNT(*) FROM ingreso WHERE usuario_id = @u
UNION ALL SELECT 'gasto', COUNT(*) FROM gasto WHERE usuario_id = @u
UNION ALL SELECT 'tarjeta', COUNT(*) FROM tarjeta WHERE usuario_id = @u
UNION ALL SELECT 'deuda', COUNT(*) FROM deuda WHERE usuario_id = @u
UNION ALL SELECT 'score_historial', COUNT(*) FROM score_historial WHERE usuario_id = @u
UNION ALL SELECT 'resumen_mensual', COUNT(*) FROM resumen_mensual WHERE usuario_id = @u
UNION ALL SELECT 'plan_msi', COUNT(*) FROM plan_msi p JOIN tarjeta t ON t.id = p.tarjeta_id WHERE t.usuario_id = @u
UNION ALL SELECT 'estado_cuenta', COUNT(*) FROM estado_cuenta e JOIN tarjeta t ON t.id = e.tarjeta_id WHERE t.usuario_id = @u
UNION ALL SELECT 'movimiento', COUNT(*) FROM movimiento m JOIN estado_cuenta e ON e.id = m.estado_cuenta_id
  JOIN tarjeta t ON t.id = e.tarjeta_id WHERE t.usuario_id = @u;
```

3. Como después del borrado las tres últimas filas dan 0 por fuerza (ya no hay tarjetas con las que unir), compara también los `COUNT(*)` totales de cada tabla antes y después: deben bajar exactamente en las filas del usuario.
4. Llama al endpoint (el token se genera con `app.core.seguridad.crear_token(id)`, ver README).

## En el dispositivo (frontend)

`src/services/dispositivo.ts` → `limpiarDispositivo()` se ejecuta solo cuando el servidor respondió 204:

- Token de sesión y claves `ikamoney:*` de `sessionStorage` y `localStorage`.
- Todas las bases de IndexedDB, entre ellas `ikamoney-offline`, las copias para consultar sin conexión (T60, ver `docs/OFFLINE.md` del frontend). Está en `BASES_CONOCIDAS` como respaldo para navegadores sin `indexedDB.databases()`.
- Las cachés de datos del service worker; se conserva `workbox-precache-*`, que es la interfaz.
- La suscripción push del navegador.

Después se cierra la sesión y la app lleva al inicio de sesión con el aviso "Tu cuenta y todos tus datos se eliminaron".

La pantalla es `/cuenta` ("Mi cuenta", ícono de la barra superior): lista lo que se pierde, avisa que no se puede deshacer, pide la contraseña y confirma en una ventana antes de borrar.

Probado el 13-nov-2026 en el navegador, en modo de prueba (`VITE_AUTH_MOCK=true`), con una base de IndexedDB, una caché de datos y claves `ikamoney:*` creadas a mano:

| Caso | Resultado |
|---|---|
| Sin contraseña | Error en el campo; no se abre la confirmación |
| Contraseña incorrecta | "La contraseña no es correcta. Tu cuenta no se eliminó."; la sesión y todos los datos siguen |
| Contraseña correcta | Lleva al inicio de sesión con el aviso; IndexedDB, caché de datos, `localStorage` y `sessionStorage` quedan vacíos; la caché `workbox-precache-*` se conserva |
| Registrar otra vez el mismo correo | Funciona |

Con T60 (copias sin conexión) se repitió el 13-nov-2026 con la base real `ikamoney-offline`, no con una creada a mano: con sesión y las copias de Balance, Score, Tarjetas y usuario guardadas, **eliminar la cuenta dejó `indexedDB.databases()` vacío**. Sin conexión, el botón "Eliminar mi cuenta" se apaga con su razón ("Sin conexión: no puedes agregar, editar ni eliminar") y `eliminarCuenta` lanza error si se intenta igual: no tendría cómo avisarle al servidor.

Pendiente por dependencias de otras tareas:

- **Pantalla contra el backend real:** el frontend ya llama a `DELETE /api/v1/cuenta`, pero no se puede iniciar sesión en modo real hasta que exista `/auth` en el backend (T51). El endpoint sí se probó de verdad (sección anterior).
- **Suscripción push real:** la app todavía no crea suscripciones. Cuando existan, repetir la prueba; el código no cambia.

## Para el aviso de privacidad (T55)

Lo que la función sí cumple y lo que no puede garantizar, para que el texto del aviso coincida:

| | |
|---|---|
| **Se borra de inmediato** | La cuenta y todos los registros de las tablas de arriba; en el dispositivo desde el que se elimina, todo lo que la app guardó |
| **No se borra: no es del usuario** | Las 9 categorías base del sistema |
| **No se borra al instante** | Lo guardado en **otros dispositivos** del usuario: su sesión deja de funcionar, pero los datos locales siguen ahí hasta que se abra la app o se borren los datos del navegador |
| **Fuera del alcance de la app** | Respaldos de la base de datos y registros (logs) del servidor, si existen. Hay que confirmar con quien administra el servidor cuánto tiempo se conservan |
| **Nunca se guardó** | El PDF del estado de cuenta: se procesa en memoria y no se escribe en disco ni en la base (T31) |
