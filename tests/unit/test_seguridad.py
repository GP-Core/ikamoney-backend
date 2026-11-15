"""Hash y verificación de contraseñas (T56)."""
from app.core.seguridad import hash_contrasena, verificar_contrasena


def test_hash_no_guarda_la_contrasena_y_cambia_cada_vez():
    a, b = hash_contrasena("Secreta 123"), hash_contrasena("Secreta 123")
    assert a.startswith("$argon2id$") and "Secreta" not in a
    assert a != b                      # sal aleatoria
    assert len(a) <= 255               # cabe en usuario.contrasena_hash


def test_verificar():
    h = hash_contrasena("Secreta 123")
    assert verificar_contrasena("Secreta 123", h) is True
    assert verificar_contrasena("secreta 123", h) is False
    assert verificar_contrasena("Secreta 123 ", h) is False   # los espacios cuentan
    assert verificar_contrasena("", h) is False


def test_hash_invalido_no_coincide_con_nada():
    for guardado in ("x", "no-usar", ""):
        assert verificar_contrasena("x", guardado) is False
        assert verificar_contrasena(guardado, guardado) is False
