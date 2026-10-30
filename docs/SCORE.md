# Índice de Salud Financiera (T35)

Motor del score de T25 (Fórmulas 11 a 14). Lo consumen el dashboard (T34), el detalle del score (T37) y las pruebas (T38). **Si la estructura de la respuesta cambia, avisar a esos tres antes.**

## 1. Endpoints

Ambos requieren token JWT y devuelven solo los datos del usuario de la sesión.

| Método y ruta | Qué devuelve |
| --- | --- |
| `GET /api/v1/score` | Score del mes en curso: puntaje, nivel y desglose por factor. Si faltan datos, la lista de lo que falta capturar. |
| `GET /api/v1/score/historial?meses=12` | Último score de cada mes (1 a 24 meses hacia atrás, incluido el actual). |

`GET` no escribe nada. El score se recalcula y se guarda en el historial en cada alta, cambio o baja de ingresos, gastos, tarjetas, MSI o deudas (T17 §3), dentro de la misma petición.

## 2. Respuesta de `GET /score`

(Ejemplo con el perfil de T25; solo se muestra un factor, la respuesta siempre trae los cinco.)

    {
      "estado": "calculado",
      "puntaje": 78,
      "puntaje_bruto": 77.5,
      "nivel": "en_revision",
      "nivel_texto": "En revisión",
      "tope_aplicado": false,
      "motivo_tope": null,
      "periodo": "2026-03",
      "version_modelo": "T25-v1",
      "factores": [
        {
          "clave": "utilizacion_credito",
          "nombre": "Utilización de crédito",
          "formula": "F12: (saldos de tarjetas + pendiente de MSI) / suma de límites × 100",
          "disponible": true,
          "peso": 25.0,
          "peso_efectivo": 25.0,
          "valor": 47.78,
          "categoria": null,
          "subpuntaje": 44.44,
          "aporte": 11.11,
          "puntos_perdidos": 13.89,
          "explicacion": "Usas el 47.8 % del límite de tus tarjetas, contando lo que falta de tus MSI. Este factor obtiene 44 de 100.",
          "como_mejorar": "Baja el saldo de tus tarjetas por debajo del 30 % de su límite.",
          "justificacion_peso": "Buró de Crédito recomienda usar menos de la mitad de la línea ...",
          "datos": { "saldo_tarjetas": 32000.0, "pendiente_msi": 11000.0, "limite_total": 90000.0 }
        }
      ],
      "orden_mejora": ["utilizacion_credito", "comportamiento_pago", "flujo_libre"],
      "faltantes": [],
      "supuestos": ["Se considera que pagas solo el mínimo de tus tarjetas (supuesto de T25), porque todavía no se captura tu forma de pago."]
    }

| Campo | Significado |
| --- | --- |
| `estado` | `calculado` o `datos_faltantes`. |
| `puntaje` | Entero de 0 a 100. `null` si faltan datos. |
| `puntaje_bruto` | Promedio ponderado antes del tope y del redondeo. |
| `nivel` | `saludable` (80–100), `en_revision` (60–79), `en_riesgo` (40–59), `critico` (0–39). Cortes fijos de T17. |
| `tope_aplicado`, `motivo_tope` | Si el score se limitó a 59 por `flujo_negativo` o `pago_con_atraso`. |
| `periodo` | Mes evaluado (AAAA-MM). |
| `version_modelo` | Versión de las reglas que calcularon el score. |
| `factores` | Siempre los cinco, en el orden de T25 (vacío si faltan datos). |
| `factores[].disponible` | `false` cuando el factor se omitió (sin tarjetas); su peso se reparte entre los demás. |
| `factores[].peso` / `peso_efectivo` | Peso configurado y peso realmente usado tras repartir los omitidos, en %. |
| `factores[].valor` | Valor del factor en % (`null` en comportamiento de pago o si se omitió). |
| `factores[].categoria` | Solo en comportamiento de pago: `pago_total`, `mas_del_minimo`, `solo_minimo`, `con_atraso`. |
| `factores[].aporte` | Puntos que suma al score. Los aportes suman `puntaje_bruto`. |
| `factores[].puntos_perdidos` | `peso_efectivo × (100 − subpuntaje) / 100` (regla 4 de T25). |
| `factores[].explicacion` | Por qué obtuvo ese subpuntaje, con el valor del usuario. |
| `factores[].como_mejorar` | Acción concreta para mejorar el factor. |
| `factores[].justificacion_peso` | Por qué el factor pesa lo que pesa (T25). |
| `factores[].datos` | Números con los que se calculó. |
| `orden_mejora` | Claves de los factores que pierden puntos, del que más pierde al que menos. |
| `faltantes` | `[{dato, obligatorio, mensaje}]`. Si alguno es obligatorio, no hay score. |
| `supuestos` | Supuestos usados en el cálculo, para mostrarlos al usuario. |

Usuario nuevo o sin ingresos: `estado` = `datos_faltantes`; `puntaje`, `puntaje_bruto`, `nivel` y `nivel_texto` en `null`; `factores`, `orden_mejora` y `supuestos` vacíos, y `faltantes` con `{"dato": "ingresos", "obligatorio": true, ...}` (y `gastos` con `obligatorio: false` si tampoco tiene gastos).

## 3. Respuesta de `GET /score/historial`

    {
      "meses": 12,
      "puntos": [
        { "periodo": "2026-03", "puntaje": 78, "nivel": "en_revision", "nivel_texto": "En revisión",
          "calculado_en": "2026-03-15T10:42:05", "version_modelo": "T25-v1" }
      ]
    }

Del mes más antiguo al más reciente. Solo aparecen los meses en los que hubo score.

## 4. Configuración de las ponderaciones

Los pesos, los puntos de referencia, los subpuntajes del comportamiento de pago, el tope y el comportamiento por defecto están en **`app/core/reglas_score.json`**, no en el código. Cada factor trae su `justificacion_peso` y la fuente de sus puntos de referencia.

| Factor | Peso | Puntos de referencia (valor % → subpuntaje) |
| --- | --- | --- |
| Relación deuda-ingreso | 30 | 0 → 100 · 30 → 100 · 40 → 50 · 50 → 0 |
| Utilización de crédito | 25 | 0 → 100 · 10 → 100 · 30 → 80 · 50 → 40 · 100 → 0 |
| Flujo libre | 25 | −20 → 0 · 0 → 40 · 20 → 100 |
| Carga de MSI | 10 | 0 → 100 · 10 → 100 · 25 → 0 |
| Comportamiento de pago | 10 | Pago total 100 · Más del mínimo 60 · Solo mínimo 20 · Con atraso 0 |
| **Total** | **100** | |

Al arrancar se valida el archivo. Si los pesos no suman 100, falta un factor, los puntos no van de menor a mayor, un subpuntaje sale de 0–100 o un peso no tiene justificación, la aplicación no arranca y dice qué está mal.

Para ajustar un peso: cambiarlo en el JSON, cuidar que sigan sumando 100, subir `version_modelo` (por ejemplo `T25-v2`) y actualizar T25 y la hoja T26 con el mismo cambio. Los niveles (cortes de T17) no son configurables.

## 5. Cómo se calcula

1. Se toma el mes en curso del motor de balance (T33): ingreso, compromisos (pagos mínimos + mensualidades MSI + otras cuotas), mensualidades MSI y flujo.
2. Se calculan los cinco factores (Fórmulas 11 a 14 y comportamiento de pago) y su subpuntaje por interpolación lineal entre puntos de referencia. Fuera del rango se usa el extremo.
3. Score bruto = Σ peso × subpuntaje ÷ Σ peso de los factores disponibles (sin tarjetas, la utilización se omite).
4. Si el flujo es negativo o el pago fue con atraso, el score bruto se limita a 59.
5. Se redondea al entero más cercano (.5 sube) y se asigna el nivel con los cortes de T17.

## 6. Cambios que hay que hacer en T25 para que coincida con el código

| # | Qué dice T25 | Qué debe decir |
| --- | --- | --- |
| 1 | Niveles: Saludable, **Atención**, **Riesgo**, Crítico | Saludable, **En revisión**, **En riesgo**, Crítico (mismos cortes, nombres de T17). Corregir también la hoja T26 y el documento de requerimientos (que dice "Estable"). |
| 2 | Los pesos son "propuesta del equipo" sin explicar cada uno | Agregar la justificación de cada peso (es el texto de `justificacion_peso` del JSON). |
| 3 | `comportamiento_pago` sale "del estado de cuenta o captura" | Mientras no exista dónde capturarlo, se usa "solo mínimo", que es el supuesto general de T25 ("el usuario paga al menos el mínimo"). |
| 4 | Regla 4: puntos perdidos = wᶠ × (100 − sᶠ) | Usar el peso efectivo cuando se omite un factor: wᶠ ÷ Σw disponibles. Con los cinco factores da lo mismo. |
| 5 | Reglas 1 (redondeo) y 2 (tope) sin orden | Primero el tope sobre el score bruto y después el redondeo, como ya lo hace la hoja T26. |
| 6 | No dice de dónde salen ingreso y flujo | Ingreso = ingresos del mes en curso, contando recurrentes; flujo = Fórmula 3, mes 1 (T33). |