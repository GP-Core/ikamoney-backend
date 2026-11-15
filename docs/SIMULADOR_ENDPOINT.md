# Endpoint del simulador de compras (T40)

`POST /api/v1/simulador/calcular` recibe la compra, valida la petición, arma los escenarios y llama al motor de T41 (`app/services/simulador.py`). No guarda nada y siempre trabaja con los datos del usuario del token. Guardar una simulación es otro endpoint.

| Capa | Archivo |
| --- | --- |
| Router (solo HTTP) | `app/api/routes/simulador.py` |
| Validación, escenarios por omisión y errores | `app/services/simulaciones.py` |
| Petición (`SimulacionPeticion`) y respuesta (`SimulacionOut`) | `app/schemas/simulacion.py` |
| Cálculo (T41, sin cambios) | `app/services/simulador.py` |

## Petición

Los nombres de los campos son los del motor, en snake_case (`tarjeta_id`, `menor_impacto`), como el resto de la API.

```json
{
  "descripcion": "Laptop",
  "precio": 9000,
  "prioridad": "media",
  "ahorro_inicial": 5000,
  "escenarios": [
    { "tipo": "contado" },
    { "tipo": "msi", "tarjeta_id": 1, "meses": 12 }
  ]
}
```

`escenarios` es opcional (de 1 a 6 si se manda). El resto de los campos y sus reglas son los de `SIMULADOR.md`.

## Escenarios por omisión

Si `escenarios` no viene (o llega vacío), se evalúan:

1. **Contado.**
2. **MSI a 3, 6, 12 y 18 meses** con la tarjeta activa de mayor crédito disponible (límite − saldo).

Sin tarjetas activas solo se evalúa de contado. Si la tarjeta elegida no alcanza para algún plazo, ese escenario regresa con `aplica: false` y su motivo. Los plazos están en `PLAZOS_POR_OMISION` (`app/services/simulaciones.py`); son los de CP-10 de T25 y están pendientes de confirmar con el equipo.

## Respuestas

| Código | Cuándo | Cuerpo |
| --- | --- | --- |
| **200** | Se calculó. Incluye los escenarios que no aplican (`aplica: false` con su `motivo`) y el estado `sin_escenarios_validos` | `SimulacionOut` |
| **400** | `SIN_INGRESOS`: no hay ingresos registrados, no se puede simular | `{codigo, mensaje, campos: [{campo: "ingresos", ...}]}` |
| **401** | Falta el token o no es válido | `NO_AUTENTICADO` |
| **404** | `TARJETA_NO_ENCONTRADA`: una tarjeta de un escenario MSI no existe o es de otro usuario | `campos[0].campo` indica el escenario, por ejemplo `escenarios.1.tarjeta_id` |
| **422** | Cuerpo inválido: precio ≤ 0 o con más de 2 decimales, prioridad desconocida, descripción vacía o de más de 120 caracteres, ahorro negativo, campo que no existe, MSI sin `tarjeta_id` o sin `meses`, contado con `tarjeta_id` o `meses`, más de 6 escenarios | `DATOS_INVALIDOS` con `campos` |

Lo que **no** es un error (200 con `aplica: false`):

- `PLAZO_NO_VALIDO`: los meses no están entre 2 y 60.
- `TARJETA_NO_DISPONIBLE`: la tarjeta es del usuario pero está inactiva.
- `LIMITE_INSUFICIENTE`: el crédito disponible no alcanza para el precio.
- `ESCENARIO_REPETIDO`: la misma forma de pago aparece dos veces.

El estado `datos_faltantes` del motor ya no llega al cliente: el endpoint lo convierte en el 400 `SIN_INGRESOS`.

## Pruebas

`tests/api/test_simulador_endpoint.py`. Para correrlas: `docker compose exec api pytest tests/api/test_simulador_endpoint.py -v`.
