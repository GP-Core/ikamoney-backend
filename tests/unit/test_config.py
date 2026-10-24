"""Pruebas unitarias de app/core/config.py: lectura de CORS_ORIGINS desde el entorno."""
from app.core.config import Settings


def _settings(monkeypatch, cors: str | None) -> Settings:
    if cors is None:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ORIGINS", cors)
    return Settings(_env_file=None)  # solo variables de entorno, sin leer ningún .env


def test_cors_por_defecto(monkeypatch):
    assert _settings(monkeypatch, None).cors_origins_list == [
        "http://localhost:5173", "https://ikamoney-dun.vercel.app"]


def test_cors_un_origen(monkeypatch):
    # Texto simple, como viene en .env.example: no debe exigir formato JSON
    assert _settings(monkeypatch, "http://localhost:5173").cors_origins_list == ["http://localhost:5173"]


def test_cors_separado_por_comas(monkeypatch):
    s = _settings(monkeypatch, " http://localhost:5173 , https://ikamoney.app,,")
    assert s.cors_origins_list == ["http://localhost:5173", "https://ikamoney.app"]  # sin espacios ni vacíos
