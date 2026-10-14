# IKAMONEY — Backend

API de IKAMONEY construida con **FastAPI**, **SQLAlchemy 2.0** y **MySQL 8**, lista para levantarse con Docker Compose.

> El frontend vive en un repositorio aparte (`ikamoney-frontend`, app de Vite que corre en `http://localhost:5173`).

> **Estado:** en desarrollo inicial. Por ahora la API expone los endpoints de salud y de prueba de conexión con la base de datos; el modelo de datos real está pendiente.

## Stack

| Capa            | Tecnología                         |
| --------------- | ---------------------------------- |
| Lenguaje        | Python 3.12                        |
| Framework web   | FastAPI 0.115 + Uvicorn            |
| ORM             | SQLAlchemy 2.0 (driver `pymysql`)  |
| Configuración   | pydantic-settings                  |
| Base de datos   | MySQL 8.0                          |
| Contenedores    | Docker + Docker Compose            |

## Requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (incluye Docker Compose), **o bien**
- Python 3.12 y un servidor MySQL 8 accesible, si quieres correrlo sin Docker.

## Configuración

Copia la plantilla `.env.example` como `.env` en la raíz del repositorio y cambia los valores:

```sh
# macOS / Linux
cp .env.example .env
```

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```

| Variable        | Obligatoria | Descripción                                                        |
| --------------- | ----------- | ------------------------------------------------------------------ |
| `MYSQL_*`       | Sí (Docker) | Credenciales y puerto con los que se crea el contenedor de MySQL.  |
| `DATABASE_URL`  | Sí          | URL de conexión de SQLAlchemy (`mysql+pymysql://...`).             |
| `CORS_ORIGINS`  | No          | Orígenes permitidos, separados por comas. Por defecto `http://localhost:5173`. |
| `AI_API_KEY`    | No          | Clave para la integración con IA (aún no se usa).                  |

> ⚠️ No subas el `.env` al repositorio: contiene contraseñas. Ya está incluido en `.gitignore`; el que se versiona es `.env.example`.

## Ejecutar con Docker (recomendado)

```sh
docker compose up --build
```

Esto levanta dos servicios:

- **api**: FastAPI en `http://localhost:8000`, con recarga automática. El código se monta como volumen, así que los cambios se ven al guardar.
- **db**: MySQL 8 en el puerto `MYSQL_PORT` (3306 por defecto). La API espera a que la base esté sana antes de arrancar.

Para detenerlo:

```sh
docker compose down        # detiene los contenedores y conserva los datos
docker compose down -v     # además borra el volumen de datos (la base se recrea desde cero)
```

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

2. Asegúrate de tener MySQL corriendo y de haber ejecutado `db/init.sql` sobre tu base.

3. Define `DATABASE_URL` apuntando a `localhost`:

   ```powershell
   # Windows (PowerShell)
   $env:DATABASE_URL = "mysql+pymysql://ikamoney:cambia_esto@localhost:3306/ikamoney"
   ```

   ```sh
   # macOS / Linux
   export DATABASE_URL="mysql+pymysql://ikamoney:cambia_esto@localhost:3306/ikamoney"
   ```

   > Por ahora la configuración busca el `.env` una carpeta por encima de este repo, así que al correrlo sin Docker lo más fiable es definir la variable a mano como arriba.

4. Desde la raíz del repo, arranca el servidor:

   ```sh
   uvicorn app.main:app --reload
   ```

## Comprobar que funciona

| Método | Ruta           | Descripción                                                     |
| ------ | -------------- | --------------------------------------------------------------- |
| GET    | `/api/health`  | Responde `{"status": "ok"}` si la API está viva (no toca la base). |
| GET    | `/api/ping-db` | Lee un mensaje de la tabla `pipeline_check` para confirmar la conexión con MySQL. |

```sh
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ping-db
```

La documentación interactiva (Swagger) está en **http://localhost:8000/docs**.

## Estructura del proyecto

```
ikamoney-backend/
├── app/
│   ├── main.py            # Crea la app, configura CORS y registra los routers bajo /api
│   ├── api/routes/        # Un router por módulo (por ahora: health.py)
│   ├── core/
│   │   ├── config.py      # Variables de entorno (pydantic-settings)
│   │   └── database.py    # Engine, sesiones y dependencia get_db
│   ├── models/            # Modelos de SQLAlchemy (pendiente)
│   ├── schemas/           # Esquemas de Pydantic (pendiente)
│   └── services/          # Lógica de negocio (pendiente)
├── db/
│   └── init.sql           # Script inicial de MySQL
├── tests/                 # Pruebas (pendiente)
├── .env.example           # Plantilla de variables de entorno (cópiala como .env)
├── .dockerignore          # Deja fuera de la imagen .env, db/, tests/, docs, etc.
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

### Agregar un módulo nuevo

1. Crea el router en `app/api/routes/<modulo>.py` con `router = APIRouter(tags=["<modulo>"])`.
2. Regístralo en `app/main.py`:

   ```python
   app.include_router(<modulo>.router, prefix="/api")
   ```

3. Para usar la base de datos en un endpoint, inyecta la sesión con `db: Session = Depends(get_db)`.

## Base de datos

- `db/init.sql` se ejecuta **solo la primera vez** que se crea el volumen de MySQL. Si lo modificas, corre `docker compose down -v` y vuelve a levantar para aplicarlo.
- La tabla `pipeline_check` es temporal y solo sirve para comprobar la conexión; se eliminará cuando existan los modelos reales.
- Todavía no hay migraciones (Alembic u otra herramienta).
