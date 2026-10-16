# Arquitectura del backend

El backend tiene tres capas. Cada petición las atraviesa en orden y cada capa solo conoce a la siguiente.

```
Petición HTTP
   │
   ▼
app/api/routes/      ROUTERS    Solo HTTP: URL, método, código de estado, parámetros.
   │                            Validan con un esquema y llaman a un servicio.
   ▼
app/services/        SERVICIOS  Reglas de negocio, consultas, commit y recálculo.
   │                            No importan FastAPI: se pueden probar sin HTTP.
   ▼
app/models/          MODELOS    Tablas de MySQL (SQLAlchemy).
```

`app/schemas/` (Pydantic) describe el JSON de entrada y de salida y lo usan routers y servicios.
`app/core/` es infraestructura: configuración, conexión, errores y seguridad.

## Estructura
```
app/
├── main.py                 # crea la app y registra los routers
├── core/
│   ├── config.py           # variables de entorno
│   ├── database.py         # engine, sesión y get_db
│   ├── errores.py          # ApiError y formato {codigo, mensaje, campos}
│   └── seguridad.py        # JWT y usuario_actual
├── api/
│   ├── deps.py             # alias Db y UsuarioActual para las firmas de los routers
│   └── routes/             # un router por recurso
│       ├── health.py  tarjetas.py  deudas.py  msi.py  movimientos.py  categorias.py
├── services/               # la lógica de negocio
│   ├── comunes.py          # obtener_del_usuario() y confirmar()
│   ├── fechas.py           # fechas de corte/pago y recurrentes del mes
│   ├── recalculo.py        # gancho de recálculo (score, historial, alertas)
│   ├── tarjetas.py  deudas.py  msi.py  movimientos.py  categorias.py
├── schemas/                # un archivo por recurso
│   ├── base.py             # Entrada, Edicion, Dinero, Tasa, EliminadoOut
│   ├── tarjeta.py  deuda.py  msi.py  movimiento.py  categoria.py
└── models/
    ├── comunes.py  usuario.py  finanzas.py  flujo.py
tests/
├── conftest.py             # base SQLite en memoria, usuarios y tokens de prueba
├── api/                    # pruebas de endpoints (HTTP completo)
└── unit/                   # pruebas de reglas y servicios, sin HTTP
```

## Reglas de cada capa
| Capa | Sí hace | No hace |
|---|---|---|
| Router | Declara la ruta, valida con el esquema, llama al servicio | Consultas, reglas de negocio, commit |
| Servicio | Reglas, consultas, `confirmar()` (flush, recálculo y commit) | Importar FastAPI, conocer HTTP |
| Esquema | Valida un campo a la vez y da forma al JSON | Tocar la base de datos |
| Modelo | Define tablas, llaves y restricciones | Reglas de negocio |

Dependencias permitidas: `routes → services → models` y `schemas` desde cualquiera de las tres.
Un servicio puede llamar a otro (por ejemplo `msi` usa `tarjetas.obtener`); un router nunca importa a otro router.

## Cómo agregar un módulo nuevo (receta)
1. **Modelo** en `app/models/` y se exporta en `app/models/__init__.py`.
2. **Esquemas** en `app/schemas/<recurso>.py`, heredando de `Entrada` y `Edicion`.
3. **Servicio** en `app/services/<recurso>.py`: funciones que reciben `(db, usuario, ...)`,
   usan `obtener_del_usuario()` para el 404 y terminan las escrituras con `confirmar(db, usuario)`.
4. **Router** en `app/api/routes/<recurso>.py`, delgado:
   ```python
   @router.post("", response_model=XOut, status_code=201)
   def crear(body: XCrear, db: Db, usuario: UsuarioActual):
       return servicio.crear(db, usuario, body)
   ```
5. **Registro** en `app/main.py`: `app.include_router(<recurso>.router, prefix="/api/v1")`.
6. **Pruebas**: reglas en `tests/unit/` y endpoints en `tests/api/`.
