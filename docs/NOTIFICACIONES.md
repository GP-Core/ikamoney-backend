# Notificaciones fuera de la app · T50

Cómo salen las alertas (T47) al correo del usuario, y cómo se dispara la revisión diaria. Contrato de las alertas: [ALERTAS.md](ALERTAS.md).

## Estado

| Pieza | Estado |
|---|---|
| Correo de alertas | Hecho y probado con un proveedor simulado. **Falta la prueba real**: llave de Brevo y remitente verificado (ver abajo) |
| Cron diario | Workflow escrito (`.github/workflows/revision-diaria.yml`). **Falta cargar los dos secretos y llevar el archivo a `main`** |
| Push (VAPID, suscripciones, service worker) | Ver el final de este documento |

## Reglas que cumple

- **Sin saldos (IC-07).** El asunto es fijo ("IKAMONEY: tienes un aviso nuevo") y el cuerpo usa el texto de la alerta, que nombra la tarjeta, el mes o la fecha, pero nunca montos. Una prueba arma un perfil con cifras reconocibles y comprueba que ninguna aparece en asunto, texto ni HTML.
- **Se respeta la configuración.** Con `canales.correo` en falso no sale nada. Al volver a prenderlo no se manda nada al instante: lo pendiente (de las últimas 48 h) sale en la siguiente revisión diaria.
- **Un aviso por alerta.** `alerta.notificada_en` marca lo enviado. Las alertas reactivadas dentro del enfriamiento (24 h) no se avisan otra vez.
- **Un solo correo por revisión**, con todas las alertas nuevas.
- **Un fallo de correo nunca rompe nada.** Si el proveedor no responde, la escritura del usuario termina bien, la alerta queda sin avisar y la revisión diaria lo reintenta durante 48 h.
- **Sin llave del proveedor no se envía nada**, y la app funciona igual.

## Cuándo se envía

1. Justo después de una escritura que **genera** alertas nuevas (`comunes.confirmar`, ya con el commit hecho). La llamada al proveedor tiene tope de 5 s (`CORREO_TIMEOUT_S`).
2. En la revisión diaria, para los pendientes y los que fallaron.

## Poner a funcionar el correo

1. Crear una cuenta en [Brevo](https://www.brevo.com) y, en *Senders*, verificar la dirección que será el remitente. Un remitente de Gmail suele caer en spam; si hay un dominio propio, conviene verificarlo con SPF y DKIM.
2. Crear una llave de API (*SMTP & API > API Keys*).
3. En el `.env` del servidor:

```
CORREO_API_KEY=xkeysib-...
CORREO_REMITENTE=avisos@tu-dominio.com
CORREO_REMITENTE_NOMBRE=IKAMONEY
```

4. Probar: bajar el umbral a 10 con `PUT /api/v1/alertas/configuracion`, tener una tarjeta con saldo, y revisar la bandeja del correo de la cuenta.

> El formato de la llamada (`POST https://api.brevo.com/v3/smtp/email`, encabezado `api-key`, cuerpo `sender` / `to` / `subject` / `htmlContent` / `textContent`) se escribió de memoria. **Confirmarlo contra la documentación de Brevo en la primera prueba real.** Si Brevo no sirve, otro proveedor es una clase nueva en `app/services/notificaciones/` que cumpla `ClienteCorreo`.

## El cron

Una llamada diaria a `POST /api/internos/revision-diaria` con la llave secreta. La ruta revisa a todos los usuarios, guarda el score del mes, crea y resuelve alertas (por ejemplo AL-03, que aparece con solo pasar los días) y envía los correos pendientes.

**Formato de la llamada** (lo que hay que acordar entre backend y cron):

```
POST {API_URL}/api/internos/revision-diaria
X-Llave-Interna: {CRON_SECRET}
```

Sin cuerpo. Responde 200 con `{usuarios_revisados, alertas_nuevas, alertas_resueltas, avisos_enviados, errores}`; 401 si la llave no coincide; 503 si el servidor no tiene `CRON_SECRET` (la ruta queda cerrada).

**Para dejarlo corriendo:**

1. Generar una llave larga: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Ponerla como `CRON_SECRET` en el `.env` del servidor y reiniciar la API.
3. En GitHub, *Settings > Secrets and variables > Actions*: `CRON_SECRET` (la misma) y `API_URL` (sin barra final).
4. **Llevar `.github/workflows/revision-diaria.yml` a `main`**: GitHub solo ejecuta los `schedule` de la rama por defecto.
5. Probarlo: pestaña *Actions > Revisión diaria de alertas > Run workflow*. Debe terminar en verde y mostrar el conteo.

Notas: GitHub puede retrasar un cron programado varios minutos en horas de mucha carga, y desactiva los programados de un repositorio sin actividad durante 60 días. Alternativa si estorba: una línea de `crontab` en la VM de Azure con el mismo `curl`.

## Push

**Pendiente.** Requiere llaves VAPID, una tabla de suscripciones, `POST` y `DELETE /notificaciones/suscripcion` y que el service worker (hoy generado por `vite-plugin-pwa` en modo `generateSW`) reciba `push`, lo que pide pasar a `injectManifest`. Es la parte más propensa a fallar (Android y iPhone se comportan distinto) y el canal obligatorio es el correo. Si no se hace esta semana, se documenta como fuera de alcance y pasa a los pendientes del sprint 10; el interruptor `canales.push` ya existe en la configuración y no hace nada hasta entonces.
