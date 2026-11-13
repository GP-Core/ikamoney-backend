# Priorizador de deudas (T43)

Ordena las tarjetas y deudas del usuario por **costo real** y dice, en dinero, por qué cada una va en su posición. Aplica la Fórmula 9 de T25 (método avalancha) y las reglas RN-18 a RN-20.

Usa el mismo motor de cálculo:
- la tasa mensual efectiva, el interés del mes y el pago mínimo salen de `app/services/formulas.py` (Fórmulas 5 y 6);
- los datos del usuario se leen con `proyeccion.preparar()` (T33).

Lo consumen la pantalla del ranking (T44) y el plan de pagos (T45). **Si la estructura cambia, avisar a los dos antes.**

## 1. Endpoint

| Método y ruta | Qué devuelve |
| --- | --- |
| `GET /api/v1/priorizador` | Ranking por costo real, deudas que no entran al ranking con su motivo, resumen de qué hacer este mes y comparación con el consejo popular. |

Requiere token JWT y devuelve solo los datos del usuario de la sesión. Solo lee: no modifica nada.

## 2. Respuesta

Perfil de ejemplo de T25 / T26 (CP-11):

```json
{
  "estado": "calculado",
  "periodo": "2026-03",
  "ranking": [
    {
      "posicion": 1, "clave": "tarjeta-1", "tipo": "tarjeta", "id": 1, "nombre": "Tarjeta A",
      "saldo": 20000.0, "tasa_anual": 60.0, "tasa_mensual": 5.8, "costo_anual_compuesto": 96.71,
      "interes_mes": 1160.0, "utilizacion": 46.67, "pago_minimo": 1460.0, "ahorro_por_mil": 58.0,
      "accion": "abonar_extra",
      "razon": "Es tu deuda más cara: liquídala primero. Con una tasa de 5.80 % al mes (96.7 % al año), este mes genera $1,160.00 de intereses. Cada $1,000 que le abones de más te ahorran $58.00 al mes.",
      "comparacion": null,
      "avisos": []
    },
    {
      "posicion": 2, "clave": "tarjeta-2", "tipo": "tarjeta", "id": 2, "nombre": "Tarjeta B",
      "saldo": 12000.0, "tasa_anual": 45.0, "tasa_mensual": 4.35, "costo_anual_compuesto": 66.69,
      "interes_mes": 522.0, "utilizacion": 50.0, "pago_minimo": 702.0, "ahorro_por_mil": 43.5,
      "accion": "pagar_minimo",
      "razon": "Va después de Tarjeta A porque su tasa es menor (4.35 % contra 5.80 % al mes): cada $1,000 abonados aquí ahorran $14.50 menos al mes que en Tarjeta A. Paga solo el mínimo ($702.00) hasta liquidar Tarjeta A. Este mes genera $522.00 de intereses.",
      "comparacion": { "contra": "tarjeta-1", "contra_nombre": "Tarjeta A", "criterio": "tasa",
                       "ahorro_por_mil_menos": 14.5 },
      "avisos": []
    }
  ],
  "sin_ranking": [
    { "clave": "msi-1", "tipo": "msi", "id": 1, "nombre": "MSI 1", "saldo": 8000.0,
      "pago_mensual": 1000.0, "motivo": "MSI",
      "mensaje": "Es a meses sin intereses: no te cobra intereses si pagas la mensualidad a tiempo, así que no entra al orden (RN-19)." }
  ],
  "resumen": "Primero cubre el mínimo de todas tus deudas ($2,162.00 en total este mes, más $2,000.00 de tus MSI). Todo el dinero extra que puedas, abónalo a Tarjeta A.",
  "intereses_mes_total": 1682.0,
  "pagos_minimos_total": 2162.0,
  "msi_mes_total": 2000.0,
  "bola_de_nieve": {
    "coincide": false, "mas_chica": "tarjeta-2", "mas_chica_nombre": "Tarjeta B",
    "diferencia_por_mil": 14.5,
    "mensaje": "Mucha gente paga primero la deuda más chica (Tarjeta B), pero te sale más caro: cada $1,000 abonados a Tarjeta B en lugar de Tarjeta A dejan $14.50 más de intereses cada mes."
  },
  "supuestos": ["…"]
}
```

| Campo | Significado |
| --- | --- |
| `estado` | `calculado`, o `sin_deudas` si ninguna deuda cobra intereses. |
| `ranking[]` | De la más cara a la más barata. `clave` es `tarjeta-<id>` o `deuda-<id>`. |
| `tasa_anual` / `tasa_mensual` / `costo_anual_compuesto` | En %. La mensual es r' de la Fórmula 5: en tarjetas lleva IVA. |
| `interes_mes` | Intereses que genera este mes con su saldo actual (Fórmula 5). |
| `utilizacion` | (saldo + lo que falta de sus MSI) ÷ límite, en %. `null` en deudas o con límite en cero. |
| `pago_minimo` | Tarjetas: Fórmula 6. Deudas: su pago mensual (`null` si no se capturó). |
| `ahorro_por_mil` | Intereses que se dejan de pagar al mes por cada $1,000 abonados a esa deuda. |
| `accion` | `abonar_extra` solo en la posición 1; las demás `pagar_minimo` (RN-20). |
| `razon` | Por qué va en esa posición, en dinero. Es el texto para la pantalla de T44. |
| `comparacion` | Contra la posición anterior: qué criterio decidió (`tasa`, `utilizacion`, `saldo` o `empate`) y cuánto menos ahorra cada $1,000. |
| `avisos[]` | `LIMITE_CERO`, `SOBRE_LIMITE`, `SIN_PAGO_MENSUAL` o `PAGO_NO_CUBRE_INTERES`. |
| `sin_ranking[]` | Lo que no se ordena: `MSI` (RN-19), `SIN_INTERESES` (tasa 0 %), `SIN_SALDO` (no se debe nada) o `SIN_TASA` (falta capturarla). |
| `resumen` | Qué hacer este mes (RN-20). |
| `pagos_minimos_total` / `msi_mes_total` | Lo que hay que cubrir sí o sí este mes. |
| `bola_de_nieve` | Comparación con pagar primero la deuda más chica. `null` con menos de dos deudas. |

## 3. Cómo se ordena

1. **Qué entra.** Se toman las tarjetas activas y las deudas activas. Las deudas liquidadas no llegan, y lo que no cobra intereses o no tiene saldo pasa a `sin_ranking`.
2. **Costo de cada una (Fórmulas 5 y 6):**
   - r' = tasa ÷ 12 × 1.16 en tarjetas, y tasa ÷ 12 en las demás deudas, igual que en la proyección;
   - interés del mes = saldo × r';
   - costo anual compuesto = (1 + r')¹² − 1;
   - pago mínimo según Banxico.
3. **Orden (Fórmula 9, RN-18).** Primero la tasa mensual más alta. Si empatan, la más usada de su límite. Si siguen empatando, la de menor saldo.
4. **Razón.** Se explica en pesos:
   - cuántos intereses genera este mes;
   - cuánto se ahorra por cada $1,000 abonados;
   - por qué va después de la anterior;
   - qué pagarle mientras tanto (RN-20).

**Por qué se ordena por tasa y no por los intereses en pesos.** Ordenar por los intereses del mes en pesos pondría primero, casi siempre, la deuda más grande, que es justo lo que RN-18 quiere evitar ("no por el monto que se debe"). La tasa dice cuánto ahorra cada peso que se abona, y por eso minimiza los intereses totales (método avalancha de T25). Los intereses en pesos sí se muestran en la razón, porque son lo que el usuario entiende.

## 4. Verificación contra T25 / T26

| Dato (CP-11) | T25 | Sistema |
| --- | --- | --- |
| Orden | 1: A · 2: B | 1: A · 2: B |
| r' mensual | 5.80 % · 4.35 % | 5.80 % · 4.35 % |
| Interés del mes | $1,160 · $522 | $1,160.00 · $522.00 |
| Utilización | 46.7 % · 50.0 % | 46.67 % · 50.00 % |
| Costo anual compuesto | 96.7 % · 66.7 % | 96.71 % · 66.69 % |
| Pago mínimo | $1,460 · $702 | $1,460.00 · $702.00 |

Los desempates de CE-08 (misma tasa: más usada primero; si empatan, menor saldo) están probados en `tests/unit/test_priorizador_reglas.py`.

## 5. Hallazgo para la validación con usuarios

En el perfil de ejemplo, el consejo popular de pagar primero la deuda más chica (Tarjeta B, $12,000) da **otro orden**. Cada $1,000 abonados a B en lugar de A dejan **$14.50 más de intereses al mes**. Con el excedente de $3,000 de CP-12 serían $43.50 al mes desde el primer mes, y la diferencia crece mientras A siga generando 5.80 % mensual. Vale la pena preguntar en la validación si los usuarios seguirían el orden por costo o el de la deuda más chica.

## 6. Decisiones y cambios para los documentos

| # | Tema | Decisión |
| --- | --- | --- |
| 1 | "Intereses ya devengados" (T43) | Se usa el interés que genera la deuda este mes (Fórmula 5), como dice REQ-PD-01 ("los intereses que genera cada mes"). Los intereses cobrados en el último estado de cuenta se podrían agregar después como dato informativo. |
| 2 | Deudas que no son tarjeta | r' = tasa ÷ 12 sin IVA, igual que las otras cuotas de la proyección (T33). T25 solo define r' para tarjetas, así que hay que agregarlo. |
| 3 | Utilización de una deuda | Las deudas no tienen límite: cuentan como 0 % en el desempate. Agregarlo a la Fórmula 9. |
| 4 | Deudas al 0 % | No entran al ranking (`SIN_INTERESES`), por la misma razón que los MSI en RN-19. Agregarlo a RN-19. |
| 5 | Tarjetas o deudas sin tasa | No se pueden ordenar sin saber cuánto cuestan: van a `sin_ranking` con `SIN_TASA` y se le pide al usuario capturarla. |
| 6 | Tarjetas inactivas | No se ordenan, igual que en la proyección y el score. |
| 7 | RN-20 | El priorizador marca `abonar_extra` solo en la posición 1 y da el total de mínimos del mes. El reparto mes a mes del excedente es T45 (Fórmula 10). |

## 7. Archivos

| Archivo | Contenido |
| --- | --- |
| `app/services/priorizador.py` | Costo real, orden, razones, exclusiones y respuesta. |
| `app/schemas/priorizador.py` | Estructura de la respuesta (este documento). |
| `app/api/routes/priorizador.py` | `GET /priorizador`. |
| `app/main.py` | Registro del router. |
| `tests/unit/test_priorizador_reglas.py`, `tests/api/test_priorizador.py` | Pruebas. |
