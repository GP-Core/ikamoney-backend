"""Piezas de prueba para estados de cuenta: PDF generados en memoria, un cliente de IA falso y una
respuesta de ejemplo. Todo con datos inventados: no se usan estados de cuenta reales ni Gemini."""
import copy
import io
import json

from pypdf import PdfReader, PdfWriter

from app.services.ia import IaNoDisponible

# Respuesta de la IA con el formato de esquema_ia.py (ejemplo_salida.json de la PoC de T08)
RESPUESTA_IA = {
    "banco": "Banco Ejemplo", "producto": None, "moneda": "MXN",
    "periodo": {"inicio": "2026-08-01", "fin": "2026-08-31"},
    "fecha_corte": "2026-08-31", "fecha_limite_pago": "2026-09-20",
    "pagos": {"total_a_pagar_periodo": 3750.0, "pago_para_no_generar_intereses": 1250.0,
              "pago_minimo": 300.0, "pago_minimo_mas_msi": 550.0},
    "credito": {"limite_credito": 20000.0, "credito_disponible": 16250.0},
    "tasas": {"cat": 65.3, "tasa_interes_anual": 48.0, "tasa_interes_mensual": None},
    "resumen_periodo": {"saldo_anterior": 1000.0, "cargos": 1000.0, "abonos": -1000.0,
                        "intereses": 0.0, "comisiones": 0.0, "iva": 0.0, "saldo_pendiente_msi": 2500.0},
    "movimientos": [
        {"fecha": "2026-08-02", "concepto": "SUPERMERCADO EJEMPLO", "monto": 1000.0,
         "tipo": "compra", "modalidad": "contado", "meses": None},
        {"fecha": "2026-08-05", "concepto": "TIENDA EJEMPLO", "monto": 250.0, "tipo": "compra",
         "modalidad": "msi", "meses": {"mensualidad_actual": 2, "meses_totales": 12,
                                       "monto_original": 3000.0, "saldo_pendiente": 2500.0}},
        {"fecha": "2026-08-10", "concepto": "PAGO RECIBIDO", "monto": -1000.0, "tipo": "pago",
         "modalidad": None, "meses": None},
    ],
}

# Texto de un estado de cuenta de prueba (sin acentos: la fuente base del PDF no los codifica)
LINEAS_ESTADO = ["ESTADO DE CUENTA", "Titular: ANA LUCIA PEREZ MUNOZ",
                 "Tarjeta 5204 1234 5678 9012", "Fecha de corte 31/08/2026",
                 "Pago minimo 300.00", "Limite de credito 20,000.00"]


def respuesta(**cambios) -> dict:
    datos = copy.deepcopy(RESPUESTA_IA)
    datos.update(cambios)
    return datos


def pdf_minimo(lineas: list[str]) -> bytes:
    """PDF de una página con texto, escrito a mano (PoC de T08)."""
    def escapar(texto):
        return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    contenido = "BT /F1 10 Tf 14 TL 50 760 Td " + " ".join(f"({escapar(l)}) '" for l in lineas) + " ET"
    objetos = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(contenido)} >>\nstream\n{contenido}\nendstream",
    ]
    salida, posiciones = "%PDF-1.4\n", []
    for numero, objeto in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f"{numero} 0 obj\n{objeto}\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n"
    salida += "".join(f"{p:010d} 00000 n \n" for p in posiciones)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n"
    return salida.encode("latin-1")


def pdf_con_contrasena(lineas: list[str]) -> bytes:
    escritor = PdfWriter()
    escritor.append(PdfReader(io.BytesIO(pdf_minimo(lineas))))
    escritor.encrypt("secreta", algorithm="AES-128")
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


class ClienteFalso:
    """Cumple ClienteIA: guarda los prompts y responde en orden (lo último se repite).

    Cada respuesta puede ser un dict (se manda como JSON), un texto o una excepción que se lanza.
    """

    def __init__(self, *respuestas):
        self.prompts: list[str] = []
        self._respuestas = list(respuestas) or [RESPUESTA_IA]

    def generar_json(self, prompt: str, esquema: dict, limite_s: float) -> str:
        self.prompts.append(prompt)
        r = self._respuestas.pop(0) if len(self._respuestas) > 1 else self._respuestas[0]
        if isinstance(r, Exception):
            raise r
        return json.dumps(r) if isinstance(r, dict) else r


SIN_TIEMPO = IaNoDisponible("se agotó el tiempo de espera")
