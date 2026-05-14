# Desacoplar Mi Perfil de modules/vacaciones

Fecha: 2026-05-14
Issue origen: `_planVacations/2026-05-14-issues-rrhh-asistencia.md` §13
Branch: feature/vacaciones

## Contexto

`modules/vacaciones/router.py` usa `prefix="/perfil"` y sirve endpoints de dos dominios distintos:

- **Transversal:** shell de Mi Perfil (`/perfil/ui`), firma digital (`/perfil/firma/*`)
- **Vacaciones:** balance, solicitudes, aprobaciones, equipo, días hábiles

Esto acopla la identidad del usuario (firma, datos laborales) a las reglas de negocio de ausencias. El objetivo es crear `modules/perfil/` como módulo propio y mover los endpoints de vacaciones a prefijo `/vacaciones/`.

## Decisiones de diseño

| Decisión | Elección |
|---|---|
| Alcance | Desacoplamiento completo |
| URLs | Nuevas `/vacaciones/*` + redirects 301 desde `/perfil/*` |
| Dependencia cruzada firma | Import directo `perfil → vacaciones` (unidireccional) |
| Issue #12 (puesto MS) | Incluido: `perfil/db_service.get_perfil_usuario()` con `puesto` |

## Regla de dependencia

```
modules/perfil → modules/vacaciones   ✅ permitido
modules/vacaciones → modules/perfil   ❌ prohibido (evitar circular)
```

La única excepción: `firma_bytes_to_base64` (1 línea) se inlinea en `vacaciones/service.py` donde se necesita para PDF, eliminando la necesidad de importar desde `perfil`.

## Archivos nuevos

```
modules/perfil/__init__.py
modules/perfil/constants.py
modules/perfil/db_service.py
modules/perfil/service.py
modules/perfil/router.py

templates/perfil/perfil.html
templates/perfil/partials/content.html
templates/perfil/partials/form_firma.html
```

## Archivos modificados

```
modules/vacaciones/router.py
modules/vacaciones/service.py
modules/vacaciones/db_service.py
modules/vacaciones/constants.py
main.py
templates/vacaciones/partials/form_solicitud.html
```

## Archivos eliminados

```
templates/vacaciones/perfil.html             → reemplazado por templates/perfil/perfil.html
templates/vacaciones/partials/content.html   → reemplazado por templates/perfil/partials/content.html
templates/vacaciones/partials/form_firma.html → reemplazado por templates/perfil/partials/form_firma.html
```

---

## Spec por archivo

### `modules/perfil/constants.py`

```python
FIRMA_MAX_BYTES = 500 * 1024  # 500 KB
```

Movido desde `modules/vacaciones/constants.py`. El resto de constantes de vacaciones permanece allá.

---

### `modules/perfil/db_service.py`

Tres funciones:

**`get_firma_usuario(conn, usuario_id: UUID) -> Optional[dict]`**
Movida desde `vacaciones/db_service.py`. Query sin cambios:
```sql
SELECT usuario_id, firma_data, tipo_firma, fecha_carga
FROM tb_usuarios_firmas WHERE usuario_id = $1
```

**`upsert_firma_usuario(conn, usuario_id: UUID, firma_bytes: bytes, tipo: str) -> None`**
Movida desde `vacaciones/db_service.py`. Query sin cambios.

**`get_perfil_usuario(conn, usuario_id: UUID) -> Optional[dict]`**
Nueva. Incluye `puesto` (issue #12):
```sql
SELECT id_usuario, nombre, email, department, puesto
FROM tb_usuarios
WHERE id_usuario = $1
```

---

### `modules/perfil/service.py`

Funciones movidas desde `vacaciones/service.py`:

- `validar_firma_png(firma_bytes: bytes) -> None` — sin cambios
- `firma_bytes_to_base64(firma_bytes: bytes) -> str` — sin cambios
- `guardar_firma(conn, usuario_id, firma_bytes, tipo, solicitud_pendiente_id=None)` — misma lógica, importa desde `perfil/db_service` y llama a vacaciones solo cuando hay `solicitud_pendiente_id`:

```python
from modules.perfil import db_service as db
from modules.perfil.constants import FIRMA_MAX_BYTES

async def guardar_firma(conn, usuario_id, firma_bytes, tipo, solicitud_pendiente_id=None):
    if len(firma_bytes) > FIRMA_MAX_BYTES:
        raise ValueError(f"La firma excede el tamaño máximo ({FIRMA_MAX_BYTES // 1024} KB)")
    validar_firma_png(firma_bytes)
    await db.upsert_firma_usuario(conn, usuario_id, firma_bytes, tipo)
    if solicitud_pendiente_id:
        from modules.vacaciones.db_service import insert_firma_solicitud
        from modules.vacaciones.service import activar_solicitud_tras_firma
        await insert_firma_solicitud(conn, solicitud_pendiente_id, usuario_id, "solicitante")
        await activar_solicitud_tras_firma(conn, solicitud_pendiente_id, usuario_id)
```

Los imports de vacaciones son locales (dentro del `if`) para hacer explícita la dependencia condicional.

---

### `modules/perfil/router.py`

Prefijo: `/perfil`. Tags: `["perfil"]`.

**Imports del router:**

```python
from modules.perfil import db_service as perfil_db
from modules.perfil import service as perfil_service
from modules.vacaciones import service as vac_service      # perfil → vacaciones ✓
from modules.vacaciones import db_service as vac_db        # perfil → vacaciones ✓
```

`/perfil/ui` necesita datos de vacaciones para el render inline del tab inicial (balance, solicitudes, tipos de ausencia, `es_jefe_o_aprobador_de_alguien`). Los endpoints de firma solo usan `perfil_db` y `perfil_service`.

**Endpoints propios:**

- `GET /perfil/ui` — shell de Mi Perfil. Misma lógica que el actual `perfil_ui` en `vacaciones/router.py`. Llama a `vac_service.get_balance_usuario`, `vac_db.get_solicitudes_usuario`, `vac_db.get_tipos_ausencia`, `vac_service.es_jefe_o_aprobador_de_alguien` y `perfil_db.get_firma_usuario`. Renderiza `templates/perfil/perfil.html` (full) o `templates/perfil/partials/content.html` (HTMX).
- `GET /perfil/firma` — renderiza `templates/perfil/partials/form_firma.html`
- `POST /perfil/firma/upload` — llama `perfil/service.guardar_firma(..., tipo="subida")`
- `POST /perfil/firma/draw` — llama `perfil/service.guardar_firma(..., tipo="dibujada")`

**Redirects 301 (GET únicamente):**

```
/perfil/balance              → /vacaciones/balance
/perfil/solicitudes          → /vacaciones/solicitudes
/perfil/solicitudes/nueva    → /vacaciones/solicitudes/nueva
/perfil/solicitudes/{id}     → /vacaciones/solicitudes/{id}
/perfil/solicitudes/{id}/pdf → /vacaciones/solicitudes/{id}/pdf
/perfil/aprobaciones         → /vacaciones/aprobaciones
/perfil/equipo               → /vacaciones/equipo
/perfil/equipo/{uid}         → /vacaciones/equipo/{uid}
```

`/perfil/dias-habiles` no necesita redirect — solo lo llama JS interno que se actualiza en el template.

Los POST (crear, cancelar, aprobar, rechazar) no tienen redirect porque no son bookmarkeables y todas las templates se actualizan a las nuevas URLs.

---

### `modules/vacaciones/router.py`

Cambios:

1. `prefix="/perfil"` → `prefix="/vacaciones"`
2. Eliminar endpoints: `perfil_ui`, `ver_firma`, `subir_firma`, `guardar_firma_dibujada`
3. Todos los endpoints de balance, solicitudes, aprobaciones, equipo y `dias-habiles` permanecen con su lógica intacta — solo cambia el prefijo de la URL.

---

### `modules/vacaciones/service.py`

Cambios:

1. Eliminar: `guardar_firma()`, `validar_firma_png()`, `firma_bytes_to_base64()`
2. Renombrar `_activar_solicitud_pendiente_firma` → `activar_solicitud_tras_firma` (quita el `_`, se vuelve pública). Cuerpo sin cambios.
3. En `generar_pdf_solicitud`, reemplazar las dos llamadas a `firma_bytes_to_base64(bytes(...))` por `base64.b64encode(bytes(...)).decode()` (inlineado, evita importar desde perfil).

---

### `modules/vacaciones/db_service.py`

Eliminar:
- `get_firma_usuario()` — movida a `perfil/db_service.py`
- `upsert_firma_usuario()` — movida a `perfil/db_service.py`

`insert_firma_solicitud()`, `completar_firma_solicitante()`, `get_firmas_solicitud()` permanecen aquí (son de dominio vacaciones).

---

### `modules/vacaciones/constants.py`

Eliminar `FIRMA_MAX_BYTES`. El resto permanece.

---

### `main.py`

Agregar registro del router de perfil antes del de vacaciones:

```python
from modules.perfil.router import router as perfil_router
app.include_router(perfil_router)

from modules.vacaciones.router import router as vacaciones_router
app.include_router(vacaciones_router)
```

---

### `templates/perfil/perfil.html`

```html
{% extends "base.html" %}
{% block title %}Enertika Core Ops | Mi Perfil{% endblock %}
{% block content %}
{% include "perfil/partials/content.html" %}
{% endblock %}
```

---

### `templates/perfil/partials/content.html`

Mismo contenido que el actual `vacaciones/partials/content.html`. Solo cambian las URLs de HTMX:

| Antes | Después |
|---|---|
| `/perfil/balance` | `/vacaciones/balance` |
| `/perfil/solicitudes` | `/vacaciones/solicitudes` |
| `/perfil/solicitudes/nueva` | `/vacaciones/solicitudes/nueva` |
| `/perfil/aprobaciones` | `/vacaciones/aprobaciones` |
| `/perfil/equipo` | `/vacaciones/equipo` |
| `/perfil/firma` | sin cambio |
| `include vacaciones/partials/balance.html` | sin cambio |

---

### `templates/perfil/partials/form_firma.html`

Movida desde `vacaciones/partials/form_firma.html`. Sin cambios de contenido (las URLs de los formularios ya apuntan a `/perfil/firma/*`).

---

### `templates/vacaciones/partials/form_solicitud.html`

Una sola línea cambia (JS fetch):

```javascript
// Antes
fetch('/perfil/dias-habiles?inicio=...')
// Después
fetch('/vacaciones/dias-habiles?inicio=...')
```

---

## Flujo de firma con solicitud pendiente

```
Usuario crea solicitud → requiere_firma=true
  → router devuelve form_firma.html con solicitud_pendiente_id

Usuario dibuja/sube firma → POST /perfil/firma/draw (o /upload)
  → perfil/router.py
  → perfil/service.guardar_firma(conn, uid, bytes, tipo, solicitud_pendiente_id)
      → perfil/db_service.upsert_firma_usuario()        [tabla: tb_usuarios_firmas]
      → vacaciones/db_service.insert_firma_solicitud()  [tabla: tb_solicitudes_firmas]
      → vacaciones/service.activar_solicitud_tras_firma() [actualiza estado, notifica]
```

---

## Qué NO cambia

- URLs visibles en sidebar y base.html: `/perfil/ui` sigue igual
- Templates de tabs de vacaciones: `balance.html`, `mis_solicitudes.html`, `aprobaciones.html`, `equipo.html`, `detalle_solicitud.html` — sin modificar
- Lógica de negocio de vacaciones: balance FIFO, periodos, aprobaciones — sin tocar
- Tabla DB: ninguna migración SQL necesaria
- Worker tasks: sin cambios

## Issue #12 incluido

`perfil/db_service.get_perfil_usuario()` incluye `puesto` de `tb_usuarios`. El campo ya se muestra en `content.html` (líneas 22–27) vía `context.puesto` que proviene de `security.py`. Este PR no agrega secciones nuevas de UI; el módulo `perfil` simplemente tiene su propia fuente de datos limpia.
