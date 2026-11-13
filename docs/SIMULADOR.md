# Simulador de compras: impacto de cada escenario (T41)

Motor que responde: *si compro esto así, ¿cómo queda mi dinero en los próximos meses y cómo queda mi score?* Aplica la Fórmula 4 de T25 y las reglas RN-15 y RN-16.

- No tiene fórmulas propias. La proyección es el motor de T33 (`formulas.proyectar`) y el score es el de T35 (`score.evaluar`).
- El veredicto lo decide este motor con reglas fijas, nunca la IA. La IA solo redacta la explicación, en otra llamada (RN-17).
- Simular no modifica nada del usuario (RN-17, REQ-SC-07).

## 1. Interfaz con T40 (endpoint)

El endpoint lo hace T40. Solo tiene que validar el cuerpo con `SimulacionPedido` y llamar al motor:

```python
from app.schemas.simulacion import SimulacionOut, SimulacionPedido
from app.services import simulador

@router.post("", response_model=SimulacionOut)
def simular(pedido: SimulacionPedido, db: Db, usuario: UsuarioActual):
    return simulador.simular(db, usuario, pedido)
```

La ruta (por ejemplo `POST /api/v1/simulaciones/calcular`) la define T40 según T17. Guardar, listar y eliminar simulaciones (REQ-SC-09) también son de T40.

### Petición

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

| Campo | Regla |
| --- | --- |
| `descripcion` | 1 a 120 caracteres. |
| `precio` | Mayor a cero, máximo dos decimales (REQ-SC-03). |
| `prioridad` | `alta`, `media` o `baja` (RN-14). |
| `ahorro_inicial` | Opcional, 0 por defecto. Es el dinero disponible hoy (Acumulado₀ de la Fórmula 3). |
| `escenarios` | De 1 a 6. Contado: `{"tipo": "contado"}`. MSI: `{"tipo": "msi", "tarjeta_id", "meses"}`. |

Un cuerpo mal formado (precio en cero, MSI sin tarjeta o sin meses, contado con meses) responde **422** con el formato de T17.

La tarjeta y el plazo **no** dan 422: si no se pueden usar, el escenario regresa con `aplica: false` y su motivo.

### Respuesta

```json
{
  "estado": "calculado",
  "periodo": "2026-03",
  "descripcion": "Laptop",
  "precio": 9000.0,
  "prioridad": "media",
  "meses": 12,
  "score_actual": { "puntaje": 78, "nivel": "en_revision", "nivel_texto": "En revisión" },
  "escenarios": [
    {
      "id": "msi-1-12", "tipo": "msi", "tarjeta_id": 1, "tarjeta_nombre": "Tarjeta A", "meses": 12,
      "aplica": true, "motivo": null,
      "mensualidad": 750.0,
      "balance": [
        { "mes": 1, "periodo": "2026-03", "ingresos": 20000.0, "gastos": 12000.0,
          "compromisos": 4912.0, "compra": 750.0, "flujo": 3088.0, "acumulado": 8088.0 }
      ],
      "indicadores": { "flujo_minimo": 3088.0, "mes_flujo_minimo": 1, "acumulado_minimo": 8088.0,
                       "meses_en_negativo": 0, "primer_mes_negativo": null },
      "score": { "puntaje": 70, "puntaje_bruto": 69.52, "nivel": "en_revision",
                 "nivel_texto": "En revisión", "tope_aplicado": false, "motivo_tope": null,
                 "cambio": -8 },
      "veredicto": "recomendable", "veredicto_texto": "Recomendable", "regla": "RN-16",
      "razon": "Tu dinero alcanza y tu índice queda en nivel En revisión.",
      "menor_impacto": true
    }
  ],
  "menor_impacto": "msi-1-12",
  "veredicto": "recomendable",
  "veredicto_texto": "Recomendable",
  "faltantes": [],
  "supuestos": ["…"],
  "version_modelo": "T25-v1"
}
```

| Campo | Significado |
| --- | --- |
| `estado` | `calculado`, `datos_faltantes` (sin ingresos: no se simula, REQ-SC-10) o `sin_escenarios_validos` (ninguno aplica). |
| `meses` | Horizonte: 12, o el plazo MSI más largo si es mayor (máximo 24). |
| `score_actual` | Score de hoy, sin la compra. |
| `escenarios[].id` | `contado` o `msi-<tarjeta_id>-<meses>`. Sirve para `menor_impacto`. |
| `escenarios[].aplica` / `motivo` | `false` con `{codigo, mensaje}` si no es viable (ver la sección 3). En ese caso `balance` está vacío y `score`, `indicadores` y `veredicto` vienen en `null`. |
| `escenarios[].mensualidad` | Contado: el precio completo este mes. MSI: precio ÷ meses. |
| `escenarios[].balance` | Mes a mes con la compra incluida. `compra` es lo que cuesta la compra ese mes y `acumulado` es el balance disponible. |
| `escenarios[].indicadores` | Los de la Fórmula 4: flujo mínimo, acumulado mínimo y meses en negativo (acumulado < 0). |
| `escenarios[].score` | Score del mes 1 con la compra hecha (motor de T35). `cambio` = simulado − actual. |
| `escenarios[].veredicto` | `recomendable`, `con_precaucion` o `no_recomendable`, con la `regla` que lo decidió y la `razon`. |
| `menor_impacto` | Id del escenario que deja mejor al usuario (ver la sección 2). |
| `veredicto` | Veredicto general: el del escenario de menor impacto. Si ninguno alcanza: "No se recomienda realizar esta compra por ahora". |

## 2. Cómo se calcula

1. **Una sola lectura de la base de datos.** `proyeccion.preparar()` (T33) lee los datos del usuario, y cada escenario reutiliza esa preparación.
2. **Mensualidad (Fórmula 4).**
   - Contado: `CompraContado₁ = precio`. No cambia la utilización.
   - MSI: un plan nuevo de `precio ÷ meses`, activo en los meses 1 a n. El precio completo ocupa la línea desde el mes 1 (T23).
3. **Proyección.** Se aplica la Fórmula 3 (motor de T33) con la compra incluida.
4. **Score del mes 1.** Se calcula con el motor de T35, suponiendo la compra hecha.
5. **Veredicto por escenario:**
   - **RN-15:** si algún mes queda con acumulado < 0, es *No recomendable por ahora*.
   - **RN-16:** si el dinero alcanza, depende de la prioridad:
     - *alta*: recomendable, aunque el índice baje;
     - *media*: recomendable si el índice no queda en En riesgo ni en Crítico;
     - *baja*: recomendable solo si el índice no baja de nivel.

     Si no se cumple la condición de su prioridad, es *Recomendable con precaución*.
6. **Menor impacto (Fórmula 4, regla 2).**
   - De los escenarios sin meses en negativo, gana el de mayor score; si empatan, el de mayor acumulado mínimo.
   - Si ninguno alcanza, gana el que deja menos meses en negativo y luego el de mayor acumulado mínimo, para que con prioridad alta se indique la opción de menor impacto (RN-15).

## 3. Escenarios que no aplican

| Código | Cuándo |
| --- | --- |
| `PLAZO_NO_VALIDO` | Los meses no están entre 2 y 60 (los mismos límites que T29). |
| `TARJETA_NO_DISPONIBLE` | La tarjeta no existe, es de otro usuario o está inactiva. |
| `LIMITE_INSUFICIENTE` | Crédito disponible < precio (REQ-SC-03). Disponible = límite − saldo − lo que falta de los MSI de esa tarjeta. |
| `ESCENARIO_REPETIDO` | La misma forma de pago viene dos veces. |

## 4. Verificación contra T25 / T26 (CP-10)

Perfil de ejemplo con una compra de $9,000, prioridad media y ahorro inicial de $5,000:

| Escenario | Mensualidad | Acumulado mínimo | Meses en negativo | Score (bruto) | Veredicto |
| --- | --- | --- | --- | --- | --- |
| Contado | 9,000.00 | −162.00 | 1 | 53 (53.11) | No recomendable (RN-15) |
| 3 MSI tarjeta A | 3,000.00 | 5,838.00 | 0 | 45 (44.87) | Con precaución (En riesgo) |
| 6 MSI tarjeta A | 1,500.00 | 7,338.00 | 0 | 64 (64.21) | Recomendable |
| **12 MSI tarjeta A** | **750.00** | **8,088.00** | **0** | **70 (69.52)** | **Recomendable** |
| 18 MSI tarjeta A | 500.00 | 8,338.00 | 0 | 71 (71.30) | Recomendable |

CP-10 de T25 pide "Contado descartado; veredicto 12 MSI (score 70)", y el motor lo cumple (`test_cp10_…`). Con 18 MSI en la comparación, el de menor impacto pasa a ser 18 MSI (71).

**Rendimiento:** 6 escenarios se calculan en unos 5 ms, sin contar la lectura de la base de datos. El requisito es menos de 2 s, y está probado en `test_responde_en_menos_de_2_segundos`.

## 5. Cambios que hay que hacer en los documentos

| # | Documento | Qué dice | Qué debe decir |
| --- | --- | --- | --- |
| 1 | RN-15 (requerimientos) | "si provoca que, en algún mes, los pagos superen los ingresos" | "si provoca que, en algún mes, el dinero disponible (acumulado) quede en negativo", como la Fórmula 4. Así una compra de contado pagada con ahorro no se descarta solo porque ese mes salga más dinero del que entra. |
| 2 | T25, Fórmula 4 | La regla del veredicto elige por score | Esa regla decide el **menor impacto**. El **veredicto** de cada escenario lo deciden RN-15 y RN-16 con la prioridad. |
| 3 | T25, Fórmula 4 | No dice qué pasa si ninguno alcanza y la prioridad es alta | Se indica el de menos meses en negativo y mayor acumulado mínimo (RN-15). |
| 4 | T25, Fórmula 4 | No dice el horizonte | 12 meses, o el plazo MSI más largo si es mayor, hasta 24. |
| 5 | T29, `credito_disponible` | límite − saldo | Debería restar también lo que falta de los MSI de la tarjeta, como el simulador; si no, la pantalla de tarjetas y el simulador muestran disponibles distintos. |
| 6 | T25, CP-10 | Score 70 (nivel Atención) | Nivel *En revisión* (nombres de T17). |

## 6. Archivos

| Archivo | Qué cambió |
| --- | --- |
| `app/services/simulador.py` | Nuevo: motor de T41. |
| `app/schemas/simulacion.py` | Nuevo: petición y respuesta (interfaz con T40). |
| `app/services/formulas.py` | La Fórmula 3 ahora incluye `CompraContado_t`, como en T25. En T33 siempre vale cero. |
| `app/services/score.py` | `_evaluar` se separó en `evaluar(prep, reglas, entrada_proyeccion, pendiente_msi_extra)` para calcular el score con la compra incluida. GET /score da lo mismo que antes. |
| `tests/unit/test_simulador_reglas.py`, `tests/api/test_simulador.py` | Pruebas. |
