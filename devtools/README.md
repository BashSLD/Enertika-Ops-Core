# Devtools de Enertika Ops Core

Suite versionada de controles deterministas para apoyar a desarrolladores y
agentes. Analiza solamente las lineas agregadas respecto de una referencia Git,
por lo que no obliga a corregir deuda historica ajena al cambio actual.

## Uso

Desde la raiz del repositorio:

```powershell
venv\Scripts\python.exe -m devtools diff
```

Para comparar contra otra referencia:

```powershell
venv\Scripts\python.exe -m devtools diff --base main
```

Para una salida estructurada consumible por agentes:

```powershell
venv\Scripts\python.exe -m devtools diff --format json
```

El pipeline mecanico ejecuta el analisis, Ruff, `py_compile` y pruebas
focalizadas a partir de los archivos modificados:

```powershell
venv\Scripts\python.exe -m devtools quality
```

Es posible omitir pytest cuando se necesita un control rapido:

```powershell
venv\Scripts\python.exe -m devtools quality --no-tests
```

## Alcance inicial

- Fechas sin zona horaria: `date.today()` y `datetime.now()`.
- Extraccion de fecha local mediante `toISOString()`.
- Capturas genericas de excepciones y `print()` en backend. `except Exception` puede
  suprimirse con el marker `# devtools: allow-broad-except` (visible, greppable);
  `except:` desnudo nunca se permite, con o sin marker.
- Firma antigua de `TemplateResponse`.
- Riesgo de `asyncio.gather()` en servicios de base de datos.
- Ternarios de cadenas en `:class` de tabs Alpine.
- Emojis en backend y UI (`EMOJI001`).
- Typo `#toast-container` en toast OOB, sin el prefijo `global-` (`HTMX002`).
- `Depends()` envolviendo `require_module_access`/`require_manager_access`, que ya retornan `Depends()` (`RBAC001`).
- `|tojson` dentro de `x-data` de Alpine (`ALPINE001`).
- SQL armado con f-strings o concatenacion en `db_service.py` (`SQL002`, heuristico).
- `EXTRACT(DOW)` sin la conversion `((... + 6) % 7)` (`TZ004`, heuristico).
- Backdrop raiz de modal sin la clase `modal-overlay-layer` (`UI001`, heuristico).
- Transicion en selector universal `* { transition }` en CSS fuente (`CSS001`).
- Deteccion de SQL que requiere `/auditar-sql diff`.
- Deteccion de clases frontend que requiere `npm run build:css`.

La suite no reemplaza `/simplify`, `/auditar-sql diff` ni `/code-review`.
Cuando detecta una accion que requiere criterio o acceso externo, la reporta
para que el agente en turno la ejecute dentro del pipeline aprobado.

## Codigos de salida

- `0`: no hay errores deterministas ni comandos fallidos.
- `1`: hay errores de reglas o fallo un comando de calidad.
- `2`: no fue posible consultar Git o ejecutar la suite.

Las advertencias y acciones pendientes se reportan, pero por si solas no
producen codigo de salida `1`.
