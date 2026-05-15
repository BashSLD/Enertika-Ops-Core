# Spec: Correcciones RRHH / Asistencia / Perfil

Fecha: 2026-05-14  
Branch: feature/vacaciones  
Alcance: Fixes sin migración SQL derivados del documento `_planVacations/2026-05-14-issues-rrhh-asistencia.md`

---

## Scope

13 issues identificados en revisión. Esta spec cubre los 12 que **no requieren migración SQL**:

| ID | Descripción corta | Complejidad |
|----|------------------|-------------|
| 2 | Feriados inicia colapsado | Trivial |
| 3 | Default asistencia = hoy | Trivial |
| 6 | Texto botón exportar empleados | Trivial |
| 8 | UUID vacío en horas extra | Trivial |
| 5a | Fix hx-target modal empleado | Simple |
| 5b | Cierre modal solo con X | Simple |
| 5c | Overlay de guardado en modal | Simple |
| 5d | Puesto Microsoft con prioridad | Simple |
| 5e | BioTime code como solo lectura | Simple |
| 10 | Firma dibujada no hace POST | Medio |
| 11 | Upload firma retorna 400 invisible | Medio |
| 12b | Puesto en Mi Perfil | Simple |
| 12c | Texto botón sync Admin más honesto | Trivial |

**Excluidos (requieren migración):** issues 1, 4, 7, 9, 13.  
**Excluido (pendiente detalles):** issue 5f (renombres y textos del modal).

---

## Grupo 1 — Fixes triviales

### Issue 2: Feriados colapsado por defecto
**Archivo:** `templates/rrhh/partials/admin.html:31`  
**Cambio:** `x-data="{ open: true }"` → `x-data="{ open: false }"`  
La sección ya es colapsable; solo cambia el estado inicial para no empujar secciones más usadas hacia abajo.

### Issue 3: Default asistencia = hoy
**Archivo:** `modules/rrhh/router.py` — función `asistencia_panel`  
**Cambio:** `fi = fecha_inicio or (hoy - timedelta(days=6))` → `fi = fecha_inicio or hoy`  
El default de 7 días es correcto para reportes; para la vista de asistencia diaria el usuario espera ver el día en curso.

### Issue 6: Texto botón exportar empleados
**Archivo:** `templates/rrhh/partials/empleados_lista.html:9`  
**Cambio:** Texto `Exportar Excel` → `Exportar reporte de vacaciones`.  
Agregar `title="Incluye saldos, periodos, días tomados, días restantes, expiración y aprobador."` al elemento `<a>`.

### Issue 8: UUID vacío en horas extra
**Archivo:** `modules/rrhh/router.py` — función `reporte_horas_extra_excel`  
**Cambio:** `usuario_id: Optional[UUID]` y `sucursal_id: Optional[UUID]` → `Optional[str] = None`.  
Convertir inline: `uid = UUID(usuario_id) if usuario_id else None`. Agregar manejo de `ValueError` para UUID malformado → `HTTPException(400)`.  
Misma corrección en `reporte_vacaciones_excel` que tiene `usuario_id: Optional[UUID]` con el mismo riesgo.

---

## Grupo 2 — Modal empleado (Issue 5)

### 5a — Fix hx-target
**Archivo:** `templates/rrhh/partials/empleado_editar.html`  
**Cambio:** `hx-target="#toast-container" hx-swap="afterbegin"` → `hx-target="this" hx-swap="none"`  
El toast llega por OOB desde `shared/toast.html` hacia `#global-toast-container`. El target ficticio `#toast-container` no existe en el DOM y dispara `htmx:targetError`.

### 5b — Cierre solo con X
**Archivo:** `templates/rrhh/partials/empleados_lista.html:82`  
**Cambio:** Eliminar `@click.outside="open = false"` del panel interior del modal.  
La X ya cierra el modal con `@click="open = false"` (línea 85). El backdrop exterior sigue visible; solo se elimina el cierre por click fuera.

### 5c — Overlay de guardado
**Archivos:** `empleados_lista.html` (x-data del modal) + `empleado_editar.html` (botón)

En `empleados_lista.html`, el `x-data` del modal pasa de `{ open: false }` a `{ open: false, saving: false }`.  
El contenedor `#empleado-modal-content` escucha:
```html
@htmx:before-request="saving = true"
@htmx:after-request="saving = false"
```

En `empleado_editar.html`, el botón Guardar:
```html
:disabled="saving"
x-text="saving ? 'Guardando...' : 'Guardar cambios'"
```

### 5d — Puesto desde Microsoft con prioridad
**Archivos:** `modules/rrhh/db_service.py` + `templates/rrhh/partials/empleado_editar.html`

`get_usuario_simple_by_id`: agregar `puesto` al SELECT de `tb_usuarios`:
```sql
SELECT id_usuario, nombre, email, department, puesto FROM tb_usuarios WHERE id_usuario = $1
```

En `empleado_editar.html`, campo Puesto:
```html
value="{{ usuario.get('puesto') or (empleado.puesto if empleado else '') }}"
```
Microsoft tiene prioridad; el valor local de `tb_empleados_datos.puesto` es fallback.

### 5e — Código BioTime como solo lectura
**Archivos:** `modules/vacaciones/db_service.py` + `templates/rrhh/partials/empleado_editar.html`

`get_empleado_datos`: agregar `biotime_emp_code` al SELECT:
```sql
SELECT id, usuario_id, numero_empleado, fecha_contratacion, puesto, departamento,
       id_aprobador_vacaciones, dias_vacaciones_ajuste, sucursal_id, biotime_emp_code
FROM tb_empleados_datos WHERE usuario_id = $1
```

En `empleado_editar.html`, agregar campo informativo debajo de "No. interno" (solo si tiene valor):
```html
{% if empleado and empleado.biotime_emp_code %}
<div>
  <label class="block text-xs font-medium text-gray-600 mb-1">Código BioTime</label>
  <p class="text-sm text-gray-400 px-3 py-2 bg-gray-50 rounded-xl">{{ empleado.biotime_emp_code }}</p>
  <p class="text-xs text-gray-400 mt-1">Sincronizado desde BioTime. No editable.</p>
</div>
{% endif %}
```

---

## Grupo 3 — Firma (Issues 10 y 11)

### Issue 10 — Firma dibujada no hace POST
**Archivo:** `templates/vacaciones/partials/form_firma.html`

**Problema raíz:** `@submit.prevent` + `htmx.trigger($el, 'submit')` crea un ciclo. El segundo submit vuelve a disparar el mismo handler de Alpine, impidiendo que HTMX tome el control.

**Fix:**
1. Quitar `@submit.prevent` del form y eliminar `htmx.trigger($el, 'submit')`.
2. El form conserva `hx-post` y deja que HTMX maneje el submit normalmente.
3. Inyectar `firma_b64` antes del envío usando `hx-on::config-request`. Como `hx-on` no tiene acceso al scope Alpine directamente, se expone la instancia en el propio elemento del form (`$el.sigPad = sigPad`) para poder leerla como `this.sigPad`:
   ```html
   hx-on::config-request="
     if (this.sigPad && !this.sigPad.isEmpty()) {
       event.detail.parameters['firma_b64'] = this.sigPad.toDataURL('image/png');
     } else {
       event.preventDefault();
     }
   "
   ```
4. Mover la instancia de SignaturePad a variable local Alpine `sigPad` (no `window._sigPad`), inicializada en `x-init` con `$nextTick`, y guardada también en `$el.sigPad`:
   ```javascript
   x-init="$nextTick(() => {
     sigPad = new SignaturePad($refs.canvas);
     $el.sigPad = sigPad;
     sigPad.addEventListener('beginStroke', () => { canvasLimpio = false; });
   })"
   ```
5. Usar `x-ref="canvas"` en el elemento `<canvas>` en lugar de `querySelector`.
6. El estado `canvasLimpio` controla si el botón está habilitado.

### Issue 11 — Upload firma retorna 400 invisible
**Archivos:** `modules/vacaciones/router.py` + `templates/vacaciones/partials/form_firma.html`

**Problema raíz:** HTMX no hace swap en respuestas 4xx; el usuario solo ve el error en consola.

**Fix en backend:** En el endpoint `subir_firma`, cambiar errores de validación de formulario (tipo, peso, dimensiones) para retornar status **200** en lugar de 400:
```python
return templates.TemplateResponse(
    request, "shared/toast.html",
    {"type": "error", "title": "Error", "message": msg},
)  # status 200, no 400
```
Errores inesperados de servidor siguen como 500.

**Fix en template:** Agregar texto de restricciones debajo del input de archivo:
```html
<p class="text-xs text-gray-400 mt-1">Solo PNG · máx. 500 KB · máx. 500 × 200 px</p>
```

---

## Grupo 4 — Puesto Microsoft en UI (Issue 12)

### 12b — Puesto en Mi Perfil
**Archivo:** `templates/vacaciones/partials/content.html`

Agregar ficha de datos laborales entre el encabezado y las pestañas, visible solo si hay valores:
```html
{% if context.department or context.puesto %}
<div class="flex gap-4 mb-4 text-sm text-gray-500">
  {% if context.puesto %}<span>{{ context.puesto }}</span>{% endif %}
  {% if context.department %}<span class="text-gray-300">·</span><span>{{ context.department }}</span>{% endif %}
</div>
{% endif %}
```
Los valores provienen del `context` del usuario (ya tiene `department`; `puesto` se agrega en 5d/`get_usuario_simple_by_id`).

**Verificar:** el endpoint `/perfil/ui` en `modules/vacaciones/router.py` ya pasa `context` al template — confirmar que incluye `puesto` del usuario (viene de `get_current_user_context` que lee `tb_usuarios`).

### 12c — Texto botón sync Admin
**Archivo:** `templates/admin/dashboard.html`

Cambiar la descripción del botón de sincronización para que sea honesta:
- Texto actual: "Sincronizar departamento y puesto desde Microsoft 365 para usuarios sin estos datos."
- Texto nuevo: "Sincronizar departamento y puesto desde Microsoft 365. Solo actualiza usuarios que aún no tienen estos datos."

No se cambia la lógica backend en esta sesión.

---

## Archivos modificados

| Archivo | Issues |
|---------|--------|
| `templates/rrhh/partials/admin.html` | 2 |
| `modules/rrhh/router.py` | 3, 8 |
| `templates/rrhh/partials/empleados_lista.html` | 5b, 5c, 6 |
| `templates/rrhh/partials/empleado_editar.html` | 5a, 5c, 5d, 5e |
| `modules/rrhh/db_service.py` | 5d |
| `modules/vacaciones/db_service.py` | 5e |
| `templates/vacaciones/partials/form_firma.html` | 10, 11 |
| `modules/vacaciones/router.py` | 11 |
| `templates/vacaciones/partials/content.html` | 12b |
| `templates/admin/dashboard.html` | 12c |

## Notas de implementación

- **Prerequisito migración 074:** Los issues 5d y 12b asumen que `tb_usuarios.puesto` existe. Según MEMORY.md, migración 074 está pendiente de aplicar. Antes de implementar, verificar con `\d tb_usuarios` o MCP si la columna ya existe. Si no existe, los SELECT fallarán con error de columna.
- **`get_current_user_context`:** Verificar que retorna `puesto` del usuario antes de usarlo en el template de perfil (12b). Si no lo retorna, agregar al SELECT de `core/security.py`.
- El campo `biotime_emp_code` existe en `tb_empleados_datos` (migración 070). Solo se agrega al SELECT; no se expone como input editable.
- El endpoint `reporte_vacaciones_excel` también tiene `usuario_id: Optional[UUID]` — corregir junto con horas extra (issue 8).
- `timedelta` ya está importado en `router.py` de rrhh; no requiere nuevo import.
- El evento `@htmx:before-request` en el modal de empleado burbujea desde el form dinámico hacia el contenedor padre — esto es correcto en HTMX 1.x y 2.x.

---

## Actualizacion de analisis previa a implementacion

Fecha: 2026-05-14

### Validacion MCP Supabase

- Se consulto `information_schema.columns` via MCP Supabase.
- Resultado: `public.tb_usuarios.puesto` existe como `character varying(150)`.
- `list_migrations` del MCP devolvio una lista vacia, por lo que para esta sesion se toma la introspeccion de columna como validacion operativa del prerequisito 074.

### Ajustes al alcance original

1. **Issue 12b requiere dos archivos adicionales**
   - `core/security_db_service.py`: agregar `puesto` al SELECT de `get_user_by_email`.
   - `core/security.py`: leer `row["puesto"]` y exponer `"puesto"` en `get_current_user_context`.

2. **Issue 8 debe cubrir todos los UUIDs query-string convertidos manualmente**
   - `reporte_asistencia_excel`
   - `reporte_vacaciones_excel`
   - `reporte_horas_extra_excel`
   - `asistencia_panel`
   - Regla: aceptar `Optional[str]`, convertir con helper local y retornar 400 en UUID malformado.

3. **Issue 10 requiere ajustar donde vive la instancia de SignaturePad**
   - La instancia debe quedar disponible para el form que dispara HTMX.
   - La implementacion debe evitar `@submit.prevent` + `htmx.trigger(...)`.
   - Se usara `hx-on::config-request` para inyectar `firma_b64` antes del POST.

4. **Issue 11 no debe cambiar el default global de `_toast_error` sin revisar otros flujos**
   - Solo los errores de validacion de firma deben responder con status 200 para que HTMX procese el toast OOB.

### Archivos adicionales agregados al alcance

| Archivo | Motivo |
|---------|--------|
| `core/security_db_service.py` | Exponer `puesto` desde `tb_usuarios` |
| `core/security.py` | Incluir `puesto` en `context` para Mi Perfil |
