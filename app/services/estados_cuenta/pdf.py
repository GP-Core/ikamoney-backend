"""Texto del PDF con pdfplumber, en memoria y sin IA: el PDF nunca sale del servidor (PoC T08)."""
import io

import pdfplumber


class PdfIlegible(Exception):
    """Tiene contraseña, está dañado o no tiene texto (por ejemplo, es un escaneo)."""


def leer_texto(contenido: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            paginas = [(pagina.extract_text() or "", bool(pagina.images)) for pagina in pdf.pages]
    except Exception as error:  # contraseña (PDFPasswordIncorrect), PDF dañado (PDFSyntaxError)...
        raise PdfIlegible(type(error).__name__) from error
    texto = "\n".join(t for t, _ in paginas)
    if not texto.strip():
        raise PdfIlegible("el PDF no tiene texto")
    if any(len(t.strip()) < 20 and imagenes for t, imagenes in paginas):
        raise PdfIlegible("hay páginas escaneadas")
    return texto
