# Desacoplar Mi Perfil de modules/vacaciones

Fecha: 2026-05-14
Issue origen: `_planVacations/2026-05-14-issues-rrhh-asistencia.md` seccion 13
Branch: `feature/vacaciones`

## Contexto

`modules/vacaciones/router.py` usa actualmente `prefix="/perfil"` y sirve endpoints de dos dominios distintos:

- Transversal: shell de Mi Perfil (`/perfil/ui`) y firma digital (`/perfil/firma/*`)
- Vacaciones: balance, solicitudes, aprobaciones, equipo y calculo de dias habiles

Esto acopla la identidad del usuario (firma, datos laborales basicos) a las reglas de negocio de ausencias. El objetivo es crear `modules/perfil/` como modulo propio, mover los endpoints operativos de vacaciones a `/vacaciones/*` y dejar `/perfil/*` como dominio transversal.

## Decisiones de diseno corregidas

| Decision | Eleccion |
|---|---|
| Alcance | Desacoplamiento completo |
| URLs | Nuevas `/vacaciones/*` + redirects 301 desde GET legacy `/perfil/*` |
| Shell de perfil | `/perfil/ui` se conserva para sidebar y navegacion principal |
| Firma digital | Endpoints propios en `modules/perfil/router.py` |
| Lectura/escritura de firma | Servicio DB compartido `modules/shared/signatures_db_service.py` |
| Dependencia perfil -> vacaciones | Permitida solo para activar solicitud pendiente tras guardar firma |
| Dependencia vacaciones -> perfil | Prohibida |
| Firma en PDF | `vacaciones/service.py` lee firmas desde `modules/shared/signatures_db_service.py` e inlinea `base64.b64encode(...)` |
| Issue #12 (puesto MS) | Incluido: `perfil/db_service.get_perfil_usuario()` con `puesto`, usado para enriquecer contexto del shell |

## Regla de dependencia

Dependencias permitidas:

```text
modules/perfil -> modules/vacaciones
modules/perfil -> modules/shared/signatures_db_service.py
modules/vacaciones -> modules/shared/signatures_db_service.py
```

Dependencia prohibida:

```text
modules/vacaciones -> modules/perfil
```

La razon de usar `modules/shared/signatures_db_service.py` es evitar que el PDF de vacaciones tenga que importar `modules.perfil`. La firma pertenece al usuario, pero tambien es requerida por el PDF de vacaciones; por eso el acceso crudo a `tb_usuarios_firmas` queda en un servicio compartido y no dentro de un dominio de negocio.

`firma_bytes_to_base64()` permanece en `modules/perfil/service.py` para UI de firma. En `modules/vacaciones/service.py`, las conversiones para PDF se hacen inline con:

```python
base64.b64encode(bytes(row["firma_data"])).decode()
```

## Archivos nuevos

```text
modules/perfil/__init__.py
modules/perfil/constants.py
modules/perfil/db_service.py
modules/perfil/service.py
modules/perfil/router.py

modules/shared/signatures_db_service.py

templates/perfil/perfil.html
templates/perfil/partials/content.html
templates/perfil/partials/form_firma.html
```

## Archivos modificados

```text
modules/vacaciones/router.py
modules/vacaciones/service.py
modules/vacaciones/db_service.py
modules/vacaciones/constants.py
main.py

templates/vacaciones/partials/form_solicitud.html
templates/vacaciones/partials/mis_solicitudes.html
templates/vacaciones/partials/detalle_solicitud.html
templates/vacaciones/partials/aprobaciones.html
templates/vacaciones/partials/equipo.html
```

## Archivos eliminados

```text
templates/vacaciones/perfil.html
templates/vacaciones/partials/content.html
templates/vacaciones/partials/form_firma.html
```

`templates/vacaciones/partials/content.html` se elimina despues de copiarlo y corregirlo como `templates/perfil/partials/content.html`.

---

## Spec por archivo

### `modules/shared/signatures_db_service.py`

Nuevo servicio DB compartido para la tabla `tb_usuarios_firmas`.

Funciones:

**`get_firma_usuario(conn, usuario_id: UUID) -> Optional[dict]`**

Movida desde `vacaciones/db_service.py`.

```sql
SELECT usuario_id, firma_data, tipo_firma, fecha_carga
FROM tb_usuarios_firmas
WHERE usuario_id = $1
```

**`upsert_firma_usuario(conn, usuario_id: UUID, firma_bytes: bytes, tipo: str) -> None`**

Movida desde `vacaciones/db_service.py`, sin cambiar la query.

Este archivo no debe importar `modules.perfil` ni `modules.vacaciones`.

---

### `modules/perfil/constants.py`

```python
FIRMA_MAX_BYTES = 500 * 1024  # 500 KB
```

Movido desde `modules/vacaciones/constants.py`. El resto de constantes de vacaciones permanece en `modules/vacaciones/constants.py`.

---

### `modules/perfil/db_service.py`

Responsable solo de datos propios del perfil.

**`get_perfil_usuario(conn, usuario_id: UUID) -> Optional[dict]`**

Incluye `puesto` para cubrir issue #12:

```sql
SELECT id_usuario, nombre, email, department, puesto
FROM tb_usuarios
WHERE id_usuario = $1
```

No debe incluir queries de firma. Las firmas viven en `modules/shared/signatures_db_service.py`.

---

### `modules/perfil/service.py`

Funciones:

- `validar_firma_png(firma_bytes: bytes) -> None`
- `firma_bytes_to_base64(firma_bytes: bytes) -> str`
- `guardar_firma(conn, usuario_id, firma_bytes, tipo, solicitud_pendiente_id=None) -> None`

Imports principales:

```python
from modules.perfil.constants import FIRMA_MAX_BYTES
from modules.shared import signatures_db_service as signatures_db
```

`guardar_firma()`:

```python
async def guardar_firma(conn, usuario_id, firma_bytes, tipo, solicitud_pendiente_id=None):
    if len(firma_bytes) > FIRMA_MAX_BYTES:
        raise ValueError(f"La firma excede el tamano maximo ({FIRMA_MAX_BYTES // 1024} KB)")
    validar_firma_png(firma_bytes)
    await signatures_db.upsert_firma_usuario(conn, usuario_id, firma_bytes, tipo)
    if solicitud_pendiente_id:
        from modules.vacaciones.db_service import insert_firma_solicitud
        from modules.vacaciones.service import activar_solicitud_tras_firma

        await insert_firma_solicitud(conn, solicitud_pendiente_id, usuario_id, "solicitante")
        await activar_solicitud_tras_firma(conn, solicitud_pendiente_id, usuario_id)
```

Los imports de vacaciones son locales dentro del `if` para hacer explicita la dependencia condicional y evitar acoplamiento al cargar el modulo.

---

### `modules/perfil/router.py`

Prefijo: `/perfil`
Tags: `["perfil"]`

Imports esperados:

```python
from modules.perfil import db_service as perfil_db
from modules.perfil import service as perfil_service
from modules.shared import signatures_db_service as signatures_db
from modules.vacaciones import db_service as vac_db
from modules.vacaciones import service as vac_service
```

`/perfil/ui` necesita datos de vacaciones para renderizar el tab inicial:

- `vac_service.get_balance_usuario`
- `vac_db.get_solicitudes_usuario`
- `vac_db.get_tipos_ausencia`
- `vac_service.es_jefe_o_aprobador_de_alguien`
- `signatures_db.get_firma_usuario`
- `perfil_db.get_perfil_usuario`

`perfil_db.get_perfil_usuario()` debe usarse para enriquecer el contexto con `nombre`, `email`, `department` y `puesto`. Si el contexto de `core/security.py` ya trae estos campos, usar perfil DB como fuente explicita del nuevo modulo y hacer fallback a `context`.

Endpoints propios:

- `GET /perfil/ui`: shell de Mi Perfil. Renderiza `templates/perfil/perfil.html` o `templates/perfil/partials/content.html` si es HTMX y no es history restore.
- `GET /perfil/firma`: renderiza `templates/perfil/partials/form_firma.html`
- `POST /perfil/firma/upload`: llama `perfil_service.guardar_firma(..., tipo="subida")`
- `POST /perfil/firma/draw`: llama `perfil_service.guardar_firma(..., tipo="dibujada")`

Redirects 301 legacy, GET unicamente:

```text
/perfil/balance              -> /vacaciones/balance
/perfil/solicitudes          -> /vacaciones/solicitudes
/perfil/solicitudes/nueva    -> /vacaciones/solicitudes/nueva
/perfil/solicitudes/{id}     -> /vacaciones/solicitudes/{id}
/perfil/solicitudes/{id}/pdf -> /vacaciones/solicitudes/{id}/pdf
/perfil/aprobaciones         -> /vacaciones/aprobaciones
/perfil/equipo               -> /vacaciones/equipo
/perfil/equipo/{uid}         -> /vacaciones/equipo/{uid}
```

`/perfil/dias-habiles` no necesita redirect porque solo lo llama JS interno que se actualiza en el template.

No agregar redirects para POST. Los POST no son bookmarkeables y todos los templates deben apuntar directamente a `/vacaciones/*` o `/perfil/firma/*`.

---

### `modules/vacaciones/router.py`

Cambios:

1. `prefix="/perfil"` -> `prefix="/vacaciones"`
2. `tags=["perfil"]` -> `tags=["vacaciones"]`
3. Eliminar endpoints de perfil/firma:
   - `perfil_ui`
   - `ver_firma`
   - `subir_firma`
   - `guardar_firma_dibujada`
4. Mantener endpoints de vacaciones con la misma logica:
   - `/dias-habiles`
   - `/balance`
   - `/solicitudes`
   - `/solicitudes/nueva`
   - `/solicitudes`
   - `/solicitudes/{solicitud_id}`
   - `/solicitudes/{solicitud_id}/cancelar`
   - `/solicitudes/{solicitud_id}/pdf`
   - `/aprobaciones`
   - `/solicitudes/{solicitud_id}/aprobar`
   - `/solicitudes/{solicitud_id}/rechazar`
   - `/equipo`
   - `/equipo/{uid}`
5. Importar firmas desde shared para validar si el usuario ya tiene firma:

```python
from modules.shared import signatures_db_service as signatures_db
```

Usos requeridos:

- En `form_nueva_solicitud()`: reemplazar `db.get_firma_usuario(...)` por `signatures_db.get_firma_usuario(...)`
- En `crear_solicitud()`, cuando `result["requiere_firma"]` sea verdadero, renderizar `templates/perfil/partials/form_firma.html`, no el template viejo de vacaciones.

---

### `modules/vacaciones/service.py`

Cambios:

1. Eliminar:
   - `guardar_firma()`
   - `validar_firma_png()`
   - `firma_bytes_to_base64()`
2. Eliminar import de `struct` si solo se usaba para validar firma.
3. Mantener import de `base64` porque el PDF lo usa.
4. Renombrar `_activar_solicitud_pendiente_firma` -> `activar_solicitud_tras_firma`.
5. En `generar_pdf_solicitud()`, reemplazar llamadas a `db.get_firma_usuario(...)` por `signatures_db.get_firma_usuario(...)`.
6. En `generar_pdf_solicitud()`, reemplazar llamadas a `firma_bytes_to_base64(...)` por conversion inline:

```python
firma_solicitante_b64 = base64.b64encode(bytes(row["firma_data"])).decode()
firma_aprobador_b64 = base64.b64encode(bytes(row["firma_data"])).decode()
```

Import esperado:

```python
from modules.shared import signatures_db_service as signatures_db
```

No importar `modules.perfil` desde este archivo.

---

### `modules/vacaciones/db_service.py`

Eliminar:

- `get_firma_usuario()`
- `upsert_firma_usuario()`

Mover ambas a `modules/shared/signatures_db_service.py`.

Permanecen aqui porque son del dominio vacaciones:

- `insert_firma_solicitud()`
- `completar_firma_solicitante()`
- `get_firmas_solicitud()`

---

### `modules/vacaciones/constants.py`

Eliminar:

```python
FIRMA_MAX_BYTES = 500 * 1024  # 500 KB
```

El resto permanece.

---

### `main.py`

Registrar el router de perfil antes del de vacaciones:

```python
from modules.perfil.router import router as perfil_router
app.include_router(perfil_router)

from modules.vacaciones.router import router as vacaciones_router
app.include_router(vacaciones_router)
```

El orden permite que `/perfil/*` quede definido por perfil y `/vacaciones/*` por vacaciones. No hay conflicto de prefijos.

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

Copiar el contenido actual de `templates/vacaciones/partials/content.html`.

Actualizar URLs:

| Antes | Despues |
|---|---|
| `/perfil/balance` | `/vacaciones/balance` |
| `/perfil/solicitudes` | `/vacaciones/solicitudes` |
| `/perfil/solicitudes/nueva` | `/vacaciones/solicitudes/nueva` |
| `/perfil/aprobaciones` | `/vacaciones/aprobaciones` |
| `/perfil/equipo` | `/vacaciones/equipo` |
| `/perfil/firma` | sin cambio |

Includes:

```html
{% include "vacaciones/partials/balance.html" %}
```

El balance sigue siendo partial de vacaciones.

---

### `templates/perfil/partials/form_firma.html`

Mover desde `templates/vacaciones/partials/form_firma.html`.

Las URLs se mantienen:

```html
hx-post="/perfil/firma/upload"
hx-post="/perfil/firma/draw"
```

No debe apuntar a `/vacaciones`.

---

### Templates de vacaciones con URLs operativas

Actualizar todas las URLs de acciones de vacaciones para que apunten a `/vacaciones/*`.

#### `templates/vacaciones/partials/form_solicitud.html`

```javascript
// Antes
fetch('/perfil/dias-habiles?inicio=...')

// Despues
fetch('/vacaciones/dias-habiles?inicio=...')
```

```html
hx-post="/vacaciones/solicitudes"
hx-get="/vacaciones/solicitudes"
```

#### `templates/vacaciones/partials/mis_solicitudes.html`

Cambiar:

```text
/perfil/solicitudes/nueva       -> /vacaciones/solicitudes/nueva
/perfil/solicitudes/{id}        -> /vacaciones/solicitudes/{id}
/perfil/solicitudes/{id}/pdf    -> /vacaciones/solicitudes/{id}/pdf
/perfil/solicitudes/{id}/cancelar -> /vacaciones/solicitudes/{id}/cancelar
```

Mantener:

```text
/perfil/firma?solicitud_pendiente_id={id}
```

#### `templates/vacaciones/partials/detalle_solicitud.html`

Cambiar:

```text
/perfil/solicitudes             -> /vacaciones/solicitudes
/perfil/solicitudes/{id}/pdf    -> /vacaciones/solicitudes/{id}/pdf
/perfil/solicitudes/{id}/cancelar -> /vacaciones/solicitudes/{id}/cancelar
/perfil/solicitudes/{id}/aprobar  -> /vacaciones/solicitudes/{id}/aprobar
/perfil/solicitudes/{id}/rechazar -> /vacaciones/solicitudes/{id}/rechazar
```

Mantener:

```text
/perfil/firma?solicitud_pendiente_id={id}
```

#### `templates/vacaciones/partials/aprobaciones.html`

Cambiar:

```text
/perfil/solicitudes/{id}         -> /vacaciones/solicitudes/{id}
/perfil/solicitudes/{id}/aprobar -> /vacaciones/solicitudes/{id}/aprobar
/perfil/solicitudes/{id}/rechazar -> /vacaciones/solicitudes/{id}/rechazar
```

#### `templates/vacaciones/partials/equipo.html`

Cambiar:

```text
/perfil/equipo/{uid} -> /vacaciones/equipo/{uid}
```

---

## Flujo de firma con solicitud pendiente

```text
Usuario crea solicitud -> requiere_firma=true
  -> vacaciones/router.py devuelve perfil/partials/form_firma.html con solicitud_pendiente_id

Usuario dibuja/sube firma -> POST /perfil/firma/draw o /perfil/firma/upload
  -> perfil/router.py
  -> perfil/service.guardar_firma(conn, uid, bytes, tipo, solicitud_pendiente_id)
      -> shared/signatures_db_service.upsert_firma_usuario()
      -> vacaciones/db_service.insert_firma_solicitud()
      -> vacaciones/service.activar_solicitud_tras_firma()
```

---

## Que NO cambia

- URL visible en sidebar y base: `/perfil/ui`
- Nombres, estructura visual y responsabilidad de los partials de vacaciones. Si cambian, solo cambian sus URLs internas:
  - `balance.html`
  - `mis_solicitudes.html`
  - `aprobaciones.html`
  - `equipo.html`
  - `detalle_solicitud.html`
- Logica de negocio de vacaciones:
  - balance FIFO
  - periodos
  - aprobaciones
  - recalculo de asistencia
- Tabla DB: no requiere migracion SQL
- Worker tasks: sin cambios

---

## Checklist de validacion posterior

Despues de implementar, ejecutar estas verificaciones:

```powershell
rg -n 'from modules\.perfil' modules\vacaciones
```

Debe devolver cero resultados.

```powershell
rg -n 'get_firma_usuario|upsert_firma_usuario' modules\vacaciones
```

Solo debe aparecer `signatures_db.get_firma_usuario(...)` en `router.py` o `service.py`; no deben existir funciones DB locales con esos nombres en `modules/vacaciones/db_service.py`.

```powershell
rg -n '"/perfil/(balance|solicitudes|aprobaciones|equipo|dias-habiles)|''/perfil/(balance|solicitudes|aprobaciones|equipo|dias-habiles)' templates modules static
```

Solo deben quedar:

- `/perfil/ui`
- `/perfil/firma`
- `/perfil/firma/upload`
- `/perfil/firma/draw`
- Redirects legacy GET en `modules/perfil/router.py`

```powershell
venv\Scripts\python.exe -m py_compile modules\perfil\router.py modules\perfil\service.py modules\perfil\db_service.py modules\shared\signatures_db_service.py modules\vacaciones\router.py modules\vacaciones\service.py modules\vacaciones\db_service.py main.py
```

---

## Issue #12 incluido

`perfil/db_service.get_perfil_usuario()` incluye `puesto` desde `tb_usuarios`.

El shell `templates/perfil/partials/content.html` debe recibir estos campos de forma explicita:

```python
perfil = await perfil_db.get_perfil_usuario(conn, usuario_id)
ctx = {
    ...
    "perfil": perfil or {},
    "context": {
        **context,
        "department": (perfil or {}).get("department") or context.get("department"),
        "puesto": (perfil or {}).get("puesto") or context.get("puesto"),
    },
}
```

Esto evita que `get_perfil_usuario()` quede como codigo muerto y deja al nuevo modulo `perfil` como fuente limpia para datos de perfil.
