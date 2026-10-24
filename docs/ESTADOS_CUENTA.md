# T31: carga y extracción de estados de cuenta con IA

Referencia de `POST /api/v1/estados-cuenta/extraer` (US 6.3). La pantalla de revisión y corrección
(T32) se construye con esta respuesta. Sigue el contrato de T17 (versión final del 09/10/2026).

El endpoint **lee el PDF, extrae sus datos y los devuelve sin guardar nada**. El guardado ocurre
solo cuando el usuario confirma (`/estados-cuenta/confirmar`, fuera de esta tarea).

---

## 1. Petición

| | |
| --- | --- |
| Método y ruta | `POST /api/v1/estados-cuenta/extraer` |
| Autenticación | `Authorization: Bearer <JWT>` (obligatoria) |
| Cuerpo | `multipart/form-data` con el campo **`archivo`** |
| Archivo | `application/pdf`, máximo **10 MB** |
| Tiempo | Hasta 30 s de IA; menos de 60 s en total |

```bash
curl -X POST http://localhost:8000/api/v1/estados-cuenta/extraer \
  -H "Authorization: Bearer $TOKEN" \
  -F "archivo=@estado.pdf;type=application/pdf"
```

Desde el frontend:

```js
const datos = new FormData();
datos.append("archivo", archivoPdf);            // File de un <input type="file" accept="application/pdf">
const r = await fetch(`${API}/api/v1/estados-cuenta/extraer`, {
  method: "POST", headers: { Authorization: `Bearer ${token}` }, body: datos,
});
```

No se fija `Content-Type` a mano: el navegador lo pone con el `boundary` del multipart.

---

## 2. Respuesta 200

```json
{
  "tarjeta": {
    "banco": "Banco Ejemplo",
    "limiteCredito": 20000.0,
    "saldoActual": 3750.0,
    "tasaAnual": 48.0,
    "pagoMinimo": 300.0,
    "pagoNoIntereses": 1250.0,
    "diaCorte": 31,
    "diaLimitePago": 20
  },
  "msi": [
    { "descripcion": "TIENDA EJEMPLO", "montoTotal": 3000.0, "meses": 12, "mensualidadesPagadas": 2 }
  ],
  "movimientos": [
    { "fecha": "2026-08-02", "concepto": "SUPERMERCADO EJEMPLO", "monto": 1000.0 }
  ]
}
```

| Campo | Tipo | De dónde sale |
| --- | --- | --- |
| `tarjeta.banco` | texto o `null` | Nombre del banco (a veces sale con la razón social, p. ej. "Nubank") |
| `tarjeta.limiteCredito` | número o `null` | Límite de crédito |
| `tarjeta.saldoActual` | número o `null` | Saldo al corte (total a pagar del periodo) |
| `tarjeta.tasaAnual` | número o `null` | Tasa de interés anual ordinaria, en % (`48.0` = 48 %) |
| `tarjeta.pagoMinimo` | número o `null` | Pago mínimo |
| `tarjeta.pagoNoIntereses` | número o `null` | Pago para no generar intereses del periodo |
| `tarjeta.diaCorte` | 1 a 31 o `null` | **Día del mes** de la fecha de corte, no la fecha completa |
| `tarjeta.diaLimitePago` | 1 a 31 o `null` | Día del mes de la fecha límite de pago |
| `msi[].descripcion` | texto | Concepto de la compra |
| `msi[].montoTotal` | número o `null` | Monto original de la compra |
| `msi[].meses` | entero o `null` | Plazo total |
| `msi[].mensualidadesPagadas` | entero o `null` | La mensualidad cobrada en este estado de cuenta ("2 de 12" ⇒ `2`) |
| `movimientos[].fecha` | `AAAA-MM-DD` | Fecha del cargo |
| `movimientos[].concepto` | texto | Concepto |
| `movimientos[].monto` | número | Monto en MXN, positivo |

Reglas:

- **Un dato que no aparece en el PDF viene como `null`.** No se inventa, no se pone `0` y la llave
  siempre está.
- Montos en MXN, como número JSON con 2 decimales.
- **`msi`** trae solo las compras a meses **sin** intereses.
- **`movimientos`** trae **solo cargos**: compras de contado, comisiones, intereses y compras a
  meses **con** intereses. No trae las mensualidades MSI (ya están en `msi`) ni los pagos,
  abonos o devoluciones, para que al guardarlos como gastos nada se cuente dos veces.
- Si el PDF no tiene movimientos, la respuesta sigue siendo 200 con listas vacías. T32 ofrece la
  captura manual.
- La extracción con IA no es 100 % confiable (T08): el usuario siempre revisa y corrige antes de
  confirmar.

---

## 3. Errores

Todos usan el formato de la API, `{"codigo", "mensaje", "campos"}`. El `mensaje` está escrito para
el usuario y siempre le recuerda que puede capturar los datos a mano.

| Código | HTTP | Cuándo |
| --- | --- | --- |
| `NO_AUTENTICADO` / `TOKEN_INVALIDO` | 401 | Falta el token o no es válido |
| `ARCHIVO_INVALIDO` | 422 | No se mandó archivo, no es PDF o pesa más de 10 MB |
| `PDF_PROTEGIDO` | 400 | El PDF tiene contraseña, está dañado o es una imagen escaneada (sin texto) |
| `NO_ES_ESTADO_DE_CUENTA` | 400 | Se leyó, pero no parece un estado de cuenta de tarjeta de crédito |
| `DATOS_SENSIBLES` | 400 | No se lograron ocultar todos los datos personales; no se envió nada a la IA |
| `IA_NO_DISPONIBLE` | 503 | La IA tardó más de 30 s, falló o respondió algo inválido. Se puede reintentar |

```json
{"codigo": "PDF_PROTEGIDO",
 "mensaje": "No pudimos leer el PDF: tiene contraseña, está dañado o es una imagen escaneada. Puedes capturar los datos a mano.",
 "campos": []}
```

---

## 4. Privacidad (IS-01 a IS-07, RN-02, RN-03, RN-08)

1. El PDF se lee **en memoria** y se cierra siempre, con o sin error. No se guarda en disco ni en
   la base.
2. Antes de llamar a la IA se borran el número de tarjeta, la CLABE, el RFC, la CURP y el nombre del
   usuario de la sesión, con o sin acentos y aunque venga partido en dos líneas. Después se
   **verifica** que no quede ninguno. Si queda algo, se cancela (`DATOS_SENSIBLES`) y no se envía
   nada.
3. Solo el texto limpio llega a Gemini. La llave (`AI_API_KEY`) vive únicamente en el servidor.
4. Nunca se piden credenciales bancarias.
5. Para datos de usuarios reales se necesita la capa de pago de Gemini: la gratuita usa la
   información para mejorar los productos de Google (hallazgo de T08).

---

## 5. Cómo está hecho

```
app/api/routes/estados_cuenta.py     Router: solo HTTP
app/schemas/estado_cuenta.py         Respuesta (camelCase, como en T17)
app/services/estados_cuenta/
  __init__.py                        extraer(): el flujo completo
  archivo.py                         Tipo, tamaño y firma %PDF; cierra el archivo siempre
  pdf.py                             Texto con pdfplumber, en memoria
  deteccion.py                       ¿Parece un estado de cuenta? (antes de la IA)
  privacidad.py                      Borrado y verificación de datos personales
  esquema_ia.py, prompt.txt          Esquema y prompt de la PoC de T08, sin cambios
  conversion.py                      Respuesta de la IA -> contrato; quita MSI repetidos (BBVA)
app/services/ia/
  base.py                            ClienteIA: la interfaz que cumple cualquier proveedor
  gemini.py                          GeminiCliente: tope de 30 s con reintentos incluidos
```

- **Cambiar de proveedor de IA:** se escribe otra clase con `generar_json(prompt, esquema,
  limite_s)` y se devuelve en `obtener_cliente_ia()` (`app/services/ia/__init__.py`). El servicio
  no cambia.
- **Configuración** (`app/core/config.py`, se puede cambiar por variable de entorno): `IA_MODELO`
  (`gemini-3.1-flash-lite`), `IA_LIMITE_S` (30), `IA_REINTENTOS_JSON` (3) y `PDF_MAX_MB` (10).
- **Pruebas:** `tests/api/test_estados_cuenta.py`, `tests/unit/test_privacidad.py`,
  `tests/unit/test_extraccion_estados.py` y `tests/unit/test_cliente_gemini.py`. Usan PDF
  generados en memoria y un cliente de IA falso: no llaman a Gemini ni usan estados de cuenta
  reales.

## 6. Prueba manual con estados de cuenta reales

Los PDF de prueba **no se versionan**. Usa los anonimizados de T08 y al menos dos bancos distintos:

1. Pon tu llave de Gemini en `AI_API_KEY` dentro de `.env` y levanta con `docker compose up -d`.
2. Genera un token (README, "Probar los endpoints") y abre `http://localhost:8000/docs`.
3. En **Authorize** pega el token. En `POST /estados-cuenta/extraer`, pulsa **Try it out**, sube
   el PDF y compara con la hoja de respuestas de T08.
4. Prueba también un PDF con contraseña y uno que no sea estado de cuenta.

## 7. Limitaciones conocidas (de T08)

- Los PDF escaneados no se procesan (no hay OCR).
- A veces la IA invierte el CAT y la tasa de interés.
- Aun con temperatura 0, la respuesta puede variar un poco entre corridas.
