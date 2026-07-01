# Lanzador local — Renovar sesión CFE MiEspacio

Permite a cualquier usuario autorizado **renovar la sesión de MiEspacio desde su PC**,
resolviendo el CAPTCHA una vez, sin depender del administrador. El script captura la
sesión (`storage_state` de Playwright) y la sube automáticamente al app.

## Por qué existe

El portal público de CFE (XML) está 100% automatizado. **MiEspacio (PDF)** exige
resolver un CAPTCHA en el login, que no se puede automatizar. El servidor del app corre
sin pantalla (Railway), así que el navegador con el CAPTCHA tiene que abrirse en una
máquina con monitor: la PC del usuario. Este lanzador hace justamente eso y elimina el
copy-paste manual del `state.json`.

## Requisitos (una sola vez)

1. **Python 3.10+** instalado.
2. Instalar dependencias:
   ```
   pip install -r requirements.txt
   ```
3. Asegurar el navegador (usa el Microsoft Edge ya instalado en Windows; si no, instálalo):
   ```
   playwright install msedge
   ```

## Uso

```
python renovar_sesion.py
```

La **primera vez** pedirá:
- **URL del app** (ej. `https://opscore.enertika.mx`)
- **Token de renovación CFE** — pídelo al equipo de sistemas (lo genera un admin en
  *Admin → Configuración Global → Recibos CFE → Token del lanzador local*).

Ambos se guardan en `cfe_config.json` junto al script para no volver a pedirlos.

Luego:
1. Se abre Edge en MiEspacio. El script pide usuario/contraseña al app con el
   token y **los autocompleta** — no necesitas conocerlos.
2. Resuelve el CAPTCHA y da clic en *Ingresar* (**único paso manual**).
3. **No cierres la ventana**: el script detecta el login solo.
4. Cuando veas *"Sesión renovada correctamente"*, listo.

Si el autocompletado falla (por ejemplo, CFE cambió el formulario o no hay
credenciales configuradas), el script cae al login manual de siempre: solo
tendrás que teclear usuario y contraseña además del CAPTCHA.

## Notas

- El `token` y el `cfe_config.json` son secretos: no los compartas ni los subas a git.
  Ya no necesitas compartir el correo/contraseña del portal MiEspacio junto con
  el token — el script los obtiene del app en tiempo real y nunca los muestra en pantalla.
- Si el token deja de funcionar, un admin lo regeneró: pide el nuevo y borra
  `cfe_config.json` para reconfigurar.
- Empaquetado como `.exe` (doble clic, sin instalar Python): pendiente de definir.
