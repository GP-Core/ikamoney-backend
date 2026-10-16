import os

# Debe existir antes de importar la app (Settings exige DATABASE_URL). Las pruebas NO usan
# esa conexión: abajo se sustituye get_db por una base SQLite en memoria.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["JWT_SECRET"] = "secreto-de-pruebas"

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401
from app.core.database import Base, get_db  # noqa: E402
from app.core.seguridad import crear_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Usuario  # noqa: E402
from app.services import fechas  # noqa: E402

HOY = date(2026, 3, 15)

test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                            poolclass=StaticPool)


@event.listens_for(test_engine, "connect")
def _activar_fk(dbapi_conn, _):  # SQLite no aplica ON DELETE CASCADE sin esto
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


TestSession = sessionmaker(bind=test_engine, autoflush=False)


def _get_db_prueba():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _get_db_prueba

TARJETA = {"nombre": "BBVA Azul", "banco": "BBVA", "ultimos_4": "1234",
           "limite_credito": 20000, "saldo_actual": 5000,
           "dia_corte": 10, "dia_pago": 30, "tasa_anual": 45.5}
DEUDA = {"nombre": "Préstamo auto", "acreedor": "Banorte", "tipo": "credito_auto",
         "monto_original": 150000, "saldo_actual": 120000, "tasa_anual": 14.9,
         "pago_mensual": 4500, "dia_pago": 5, "fecha_inicio": "2025-01-05"}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setattr(fechas, "hoy_mx", lambda: HOY)  # "hoy" fijo: 15-mar-2026
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield


def _usuario(correo: str):
    with TestSession() as db:
        u = Usuario(nombre="Prueba", correo=correo, contrasena_hash="x", moneda="MXN")
        db.add(u)
        db.commit()
        return u.id, {"Authorization": f"Bearer {crear_token(u.id)}"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def usuario1():
    return _usuario("uno@ejemplo.com")


@pytest.fixture
def h(usuario1):
    return usuario1[1]


@pytest.fixture
def h2():
    return _usuario("dos@ejemplo.com")[1]


@pytest.fixture
def tarjeta(client, h):
    r = client.post("/api/v1/tarjetas", json=TARJETA, headers=h)
    assert r.status_code == 201, r.text
    return r.json()
