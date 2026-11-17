"""Texto del correo de alertas. IC-07: nada de saldos, límites ni montos, ni en el asunto (se ve en la
bandeja) ni en el cuerpo. Las alertas ya se guardan sin cifras; aquí solo se arma el mensaje."""
from html import escape

ASUNTO_UNO = "IKAMONEY: tienes un aviso nuevo"
ASUNTO_VARIOS = "IKAMONEY: tienes avisos nuevos"


def armar(nombre: str, alertas: list, enlace: str) -> tuple[str, str, str]:
    """(asunto, texto, html) para una o varias alertas con `titulo`, `mensaje` y `accion`."""
    asunto = ASUNTO_UNO if len(alertas) == 1 else ASUNTO_VARIOS
    saludo = f"Hola {nombre}," if nombre else "Hola,"
    cierre = "Entra a IKAMONEY para ver el detalle:"
    pie = "Puedes cambiar o apagar estos avisos en la configuración de alertas de la app."

    texto = [saludo, ""]
    for a in alertas:
        texto += [f"- {a.titulo}", f"  {a.mensaje}", f"  {a.accion}", ""]
    texto += [cierre, enlace, "", pie]

    items = "".join(
        f"<li style=\"margin-bottom:12px\"><strong>{escape(a.titulo)}</strong><br>"
        f"{escape(a.mensaje)}<br><em>{escape(a.accion)}</em></li>" for a in alertas)
    html = (f"<p>{escape(saludo)}</p><ul style=\"padding-left:18px\">{items}</ul>"
            f"<p>{cierre} <a href=\"{escape(enlace, quote=True)}\">abrir mis alertas</a></p>"
            f"<p style=\"color:#666;font-size:13px\">{pie}</p>")
    return asunto, "\n".join(texto), html
