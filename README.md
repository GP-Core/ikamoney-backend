# IKAMONEY — Backend

API de IKAMONEY construida con **FastAPI**, **SQLAlchemy 2.0** y **MySQL 8**, lista para levantarse con Docker Compose.

> El frontend vive en un repositorio aparte (`ikamoney-frontend`, app de Vite que corre en `http://localhost:5173`).

Incluye los endpoints de tarjetas, deudas, planes MSI, ingresos y gastos (fijos y variables) y categorías, cuyo detalle está en [`docs/IMPLEMENTACION.md`](docs/IMPLEMENTACION.md), y la lectura de estados de cuenta en PDF con IA, descrita en [`docs/ESTADOS_CUENTA.md`](docs/ESTADOS_CUENTA.md).

## Stack

| Capa            | Tecnología                         |
| --------------- | ---------------------------------- |
| Lenguaje        | Python 3.12                        |
| Framework web   | FastAPI 0.115 + Uvicorn            |
| ORM             | SQLAlchemy 2.0 (driver `pymysql`)  |
| Autenticación   | JWT (PyJWT)                        |
| Configuración   | pydantic-settings                  |
| Base de datos   | MySQL 8.0                          |
| Pruebas         | pytest + httpx                     |
| Contenedores    | Docker + Docker Compose            |

---

## Puesta en marcha (desde cero)

### Requisitos

- [Git](https://git-scm.com/downloads)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (incluye Docker Compose). **Ábrelo y espera a que diga "Engine running"** antes de seguir.

### 1. Clonar el repositorio

```sh
git clone https://github.com/GP-Core/ikamoney-backend.git
cd ikamoney-backend
```

Si el trabajo está en una rama distinta de la principal, cámbiate a ella:

```sh
git checkout <nombre-de-la-rama>
```

### 2. Crear el archivo `.env`

El `.env` guarda contraseñas y **no se sube al repositorio**, así que cada persona crea el suyo a partir de la plantilla:

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```

```sh
# macOS / Linux
cp .env.example .env
```

Abre `.env` y cambia los valores `cambia_esto`:

| Variable | Qué poner |
| --- | --- |
| `MYSQL_ROOT_PASSWORD` | Contraseña del usuario root de MySQL |
| `MYSQL_DATABASE` | Nombre de la base. Déjalo en `ikamoney` |
| `MYSQL_USER` / `MYSQL_PASSWORD` | Usuario y contraseña de la aplicación |
| `MYSQL_PORT` | Puerto de MySQL **en tu computadora**. Por defecto `3307`; si ya lo usas, cámbialo |
| `DATABASE_URL` | `mysql+pymysql://<MYSQL_USER>:<MYSQL_PASSWORD>@db:3306/<MYSQL_DATABASE>` |
| `JWT_SECRET` | Una cadena larga y aleatoria para firmar los tokens |
| `CORS_ORIGINS` | Orígenes del frontend, separados por comas (por defecto `http://localhost:5173`) |
| `AI_API_KEY` | Llave de la API de Gemini para leer estados de cuenta. Sin ella, `/estados-cuenta/extraer` responde 503 |

Dos detalles de `DATABASE_URL`:

- El host es **`db`** (el nombre del servicio en Docker) y el puerto es **`3306`**, el interno del contenedor. No lleva `MYSQL_PORT`.
- Usuario, contraseña y base deben coincidir con las variables `MYSQL_*` de arriba.

Ejemplo:

```env
MYSQL_ROOT_PASSWORD=RootSegura123
MYSQL_DATABASE=ikamoney
MYSQL_USER=ikamoney
MYSQL_PASSWORD=ClaveApp456
MYSQL_PORT=3307
DATABASE_URL=mysql+pymysql://ikamoney:ClaveApp456@db:3306/ikamoney
CORS_ORIGINS=http://localhost:5173
AI_API_KEY=
JWT_SECRET=pon-aqui-una-cadena-larga-y-aleatoria
```

### 3. Levantar los contenedores

```sh
docker compose up --build -d
```

Esto crea dos servicios:

- **api**: FastAPI en `http://localhost:8000`, con recarga automática (el código se monta como volumen).
- **db**: MySQL 8. La API espera a que la base esté sana antes de arrancar; la primera vez puede tardar unos 30 segundos.

Comprueba que ambos estén arriba:

```sh
docker compose ps
```

### 4. Crear las tablas

```sh
docker compose exec api python -m app.crear_tablas
```

Crea las tablas que falten y siembra las 9 categorías base (Vivienda, Alimentación, Transporte, Servicios, Salud, Educación, Entretenimiento, Compras y Otros). Se puede repetir sin problema: no duplica nada.

### 5. Comprobar que funciona

```sh
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ping-db
```

En PowerShell, si `curl` da problemas, usa `curl.exe` o abre las rutas en el navegador.

| Ruta | Respuesta esperada |
| --- | --- |
| `/api/health` | `{"status":"ok"}` |
| `/api/ping-db` | Un mensaje que confirma la conexión con MySQL |

La documentación interactiva (Swagger) está en **http://localhost:8000/docs**.

### 6. Correr las pruebas

```sh
docker compose exec api pytest -v
```

Deben pasar las 247 pruebas. Usan SQLite en memoria, así que no tocan tu base de MySQL, y un cliente de IA falso, así que no llaman a Gemini.

---

## Probar los endpoints

Todos los endpoints de `/api/v1` exigen un token JWT. El módulo de registro e inicio de sesión (`/auth`) es de otra tarea, así que por ahora se crea un usuario de prueba y un token a mano.

**1. Crear un usuario de prueba y generar su token** (PowerShell):

```powershell
@'
from app.core.database import SessionLocal
from app.core.seguridad import crear_token
from app.models import Usuario

with SessionLocal() as db:
    u = Usuario(nombre="Demo", correo="demo@ikamoney.dev", contrasena_hash="no-usar")
    db.add(u)
    db.commit()
    print(crear_token(u.id))
'@ | docker compose exec -T api python -
```

En macOS / Linux, el mismo script con un heredoc:

```sh
docker compose exec -T api python - <<'EOF'
from app.core.database import SessionLocal
from app.core.seguridad import crear_token
from app.models import Usuario

with SessionLocal() as db:
    u = Usuario(nombre="Demo", correo="demo@ikamoney.dev", contrasena_hash="no-usar")
    db.add(u)
    db.commit()
    print(crear_token(u.id))
EOF
```

Imprime un texto largo: ese es el token. Dura 24 horas. Si ya creaste el usuario y solo necesitas otro token, cambia `Usuario(...)` y `db.add/commit` por `crear_token(1)`, con el id del usuario.

**2. Usarlo en Swagger:** abre `http://localhost:8000/docs`, pulsa **Authorize**, pega el token y confirma. Ya puedes probar cualquier endpoint con **Try it out**.

**3. Usarlo con `curl`:**

```sh
TOKEN="<pega-el-token>"
curl http://localhost:8000/api/v1/categorias -H "Authorization: Bearer $TOKEN"
```

Los `id` de categorías, tarjetas y demás son **números reales** que devuelve la API. No uses texto como `ID_VIVIENDA`: consulta primero `GET /categorias`.

Más ejemplos con cada endpoint: [`docs/IMPLEMENTACION.md`](docs/IMPLEMENTACION.md). Para subir un estado de cuenta: [`docs/ESTADOS_CUENTA.md`](docs/ESTADOS_CUENTA.md).

---

## Comandos del día a día

```sh
docker compose up -d                 # arrancar
docker compose logs -f api           # ver los logs de la API
docker compose down                  # detener y conservar los datos
docker compose down -v               # detener y BORRAR la base (se recrea desde cero)
docker compose exec api pytest -v    # correr las pruebas
```

Si borras el volumen con `down -v`, vuelve a ejecutar el paso 4 (crear tablas) y a crear el usuario de prueba.

## Ver la base de datos con MySQL

```powershell
# PowerShell: lista las tablas
"SHOW TABLES;" | docker compose exec -T db sh -c 'mysql -u root -p$MYSQL_ROOT_PASSWORD ikamoney'
```

También puedes conectarte con un cliente gráfico (MySQL Workbench, DBeaver) a `localhost`, con el puerto `MYSQL_PORT` de tu `.env` y el usuario de la aplicación.

## Problemas frecuentes

| Síntoma | Causa y solución |
| --- | --- |
| `500 Internal Server Error` al levantar o `error during connect` | Docker Desktop no está corriendo. Ábrelo, espera a que arranque y repite |
| `ports are not available: ... 3306` (o 3307) | Otro programa usa ese puerto. Cambia `MYSQL_PORT` en `.env` y repite `docker compose up -d` |
| El contenedor `db` sale con `exited (1)` o `(2)` y los logs hablan de *redo log* | El volumen de MySQL se corrompió. Corre `docker compose down -v` y vuelve a levantar |
| `Access denied for user` | `DATABASE_URL` no coincide con `MYSQL_USER` / `MYSQL_PASSWORD`. Si cambiaste las contraseñas después de crear el volumen, haz `docker compose down -v` |
| `Table '...' doesn't exist` | Falta el paso 4: `docker compose exec api python -m app.crear_tablas` |
| `401 NO_AUTENTICADO` / `TOKEN_INVALIDO` | Falta el token, venció (24 h) o se firmó con otro `JWT_SECRET`. Genera uno nuevo |
| `404` al consultar un id | El id no existe o es de otro usuario. Consulta primero el listado |
| `422` con `ID_...` en el cuerpo | Se mandó un texto de ejemplo en lugar de un número real |

---

## Ejecutar sin Docker

1. Crea y activa un entorno virtual e instala las dependencias:

   ```sh
   python -m venv .venv
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   # macOS / Linux
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

2. Ten un MySQL 8 corriendo con la base y el usuario de tu `.env`.

3. Define las variables apuntando a `localhost` (con el puerto que expone MySQL en tu máquina):

   ```powershell
   # Windows (PowerShell)
   $env:DATABASE_URL = "mysql+pymysql://ikamoney:ClaveApp456@localhost:3307/ikamoney"
   $env:JWT_SECRET = "pon-aqui-una-cadena-larga-y-aleatoria"
   ```

   ```sh
   # macOS / Linux
   export DATABASE_URL="mysql+pymysql://ikamoney:ClaveApp456@localhost:3307/ikamoney"
   export JWT_SECRET="pon-aqui-una-cadena-larga-y-aleatoria"
   ```

   > La configuración busca el `.env` una carpeta por encima de este repo, así que sin Docker lo más fiable es definir las variables a mano como arriba.

4. Crea las tablas y arranca el servidor desde la raíz del repo:

   ```sh
   python -m app.crear_tablas
   uvicorn app.main:app --reload
   ```

5. Para las pruebas: `pytest -v`.

---

## Estructura del proyecto

El backend tiene tres capas (router, servicio, modelo). El detalle y las reglas de cada una están en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

```
ikamoney-backend/
├── app/
│   ├── main.py            # Crea la app, configura CORS y registra los routers
│   ├── crear_tablas.py    # Crea las tablas y siembra las categorías base
│   ├── api/
│   │   ├── deps.py        # Alias Db y UsuarioActual para los routers
│   │   └── routes/        # Un router por recurso: solo HTTP
│   ├── services/          # Lógica de negocio (reglas, consultas, commit)
│   ├── schemas/           # Esquemas de Pydantic, uno por recurso
│   ├── models/            # Modelos de SQLAlchemy
│   └── core/              # Configuración, base de datos, errores y seguridad
├── db/
│   └── init.sql           # Script inicial de MySQL
├── tests/
│   ├── api/               # Pruebas de endpoints
│   └── unit/              # Pruebas de reglas y servicios, sin HTTP
├── docs/                  # Arquitectura y documentación de los endpoints
├── .env.example           # Plantilla de variables de entorno (cópiala como .env)
├── .dockerignore
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pytest.ini
└── requirements.txt
```

### Agregar un módulo nuevo

Sigue la receta de [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md): modelo, esquemas, servicio, router (delgado), registro en `app/main.py` y pruebas.

## Base de datos

- `db/init.sql` se ejecuta **solo la primera vez** que se crea el volumen de MySQL. Si lo modificas, corre `docker compose down -v` y vuelve a levantar.
- La tabla `pipeline_check` es temporal y solo sirve para el endpoint `/api/ping-db`.
- Las tablas del negocio las crea `app/crear_tablas.py` con SQLAlchemy.
- Todavía no hay migraciones (Alembic u otra herramienta).
