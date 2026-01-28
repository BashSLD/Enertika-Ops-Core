# 7. WorkflowService - Sistema Centralizado de Comentarios

## Propósito

`WorkflowService` es un servicio centralizado en `core/workflow/` que gestiona:
- Comentarios unificados entre módulos
- Notificaciones inteligentes por email
- Historial completo de interacciones

**Ubicación**: `core/workflow/service.py`

## 📋 API de WorkflowService

### 1. `add_comentario()`

Crea un comentario y envía notificaciones automáticas.

**Firma**:
```python
async def add_comentario(
    self,
    conn,                    # Conexión a BD
    user_context: dict,      # Contexto del usuario actual
    id_oportunidad: UUID,    # ID de la oportunidad
    comentario: str,         # Texto del comentario
    departamento_slug: str,  # "SIMULACION", "COMERCIAL", "INGENIERIA"
    modulo_origen: str       # "simulacion", "comercial", "ingenieria"
) -> dict
```

**Ejemplo de Uso**:
```python
# En tu router
from core.workflow.service import get_workflow_service

@router.post("/comentarios/{id_oportunidad}")
async def create_comentario(
    id_oportunidad: UUID,
    nuevo_comentario: str = Form(...),
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("tu_modulo", "editor")
):
    if nuevo_comentario.strip():
        await workflow_service.add_comentario(
            conn, context, id_oportunidad, nuevo_comentario,
            departamento_slug="TU_DEPARTAMENTO",
            modulo_origen="tu_modulo"
        )
    
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    return templates.TemplateResponse("shared/partials/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios
    })
```

**¿Qué hace internamente?**:
1. Inserta comentario en `tb_comentarios_workflow`
2. Determina destinatarios (solicitante ↔ responsable)
3. Agrega CC desde `tb_config_emails`
4. Envía email usando template HTML
5. **No bloquea** si falla el email (fire & forget)

### 2. `get_historial()`

Obtiene el historial completo de comentarios.

**Firma**:
```python
async def get_historial(
    self,
    conn,
    id_oportunidad: UUID,
    limit: Optional[int] = None
) -> List[dict]
```

**Ejemplo de Uso**:
```python
@router.get("/partials/comentarios/{id_oportunidad}")
async def get_comentarios_partial(
    id_oportunidad: UUID,
    request: Request,
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection)
):
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    return templates.TemplateResponse("shared/partials/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios
    })
```

**Retorna**:
```python
[
    {
        "id": UUID,
        "usuario_nombre": "Juan Pérez",
        "usuario_email": "juan@enertika.com",
        "comentario": "Texto del comentario",
        "departamento_origen": "SIMULACION",
        "modulo_origen": "simulacion",
        "fecha_comentario": datetime
    },
    ...
]
```

## Integración en Nuevos Módulos

### Paso 1: Importar en Router

```python
# modules/tu_modulo/router.py
from core.workflow.service import get_workflow_service
```

### Paso 2: Crear Endpoints

**POST - Crear Comentario**:
```python
@router.post("/comentarios/{id_oportunidad}")
async def create_comentario(
    id_oportunidad: UUID,
    request: Request,
    nuevo_comentario: str = Form(...),
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = require_module_access("tu_modulo", "editor")
):
    """Crea un nuevo comentario y devuelve la lista actualizada."""
    logger.info(f"[ROUTER] Recibido POST comentario para {id_oportunidad}")
    
    if nuevo_comentario.strip():
        await workflow_service.add_comentario(
            conn, context, id_oportunidad, nuevo_comentario,
            departamento_slug="TU_DEPARTAMENTO",  # Cambiar según módulo
            modulo_origen="tu_modulo"              # Cambiar según módulo
        )
    
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    return templates.TemplateResponse("shared/partials/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios
    })
```

**GET - Mostrar Historial**:
```python
@router.get("/partials/comentarios/{id_oportunidad}", include_in_schema=False)
async def get_comentarios_partial(
    id_oportunidad: UUID,
    request: Request,
    workflow_service = Depends(get_workflow_service),
    conn = Depends(get_db_connection),
    _ = require_module_access("tu_modulo")
):
    """Partial: Lista de comentarios."""
    comentarios = await workflow_service.get_historial(conn, id_oportunidad)
    return templates.TemplateResponse("shared/partials/comentarios_list.html", {
        "request": request,
        "comentarios": comentarios
    })
```

### Paso 3: UI - Formulario de Comentarios

**Template Ejemplo** (`templates/tu_modulo/partials/comentarios_section.html`):
```html
<div class="bg-white rounded-lg p-4 border border-gray-200">
    <h4 class="font-bold text-gray-800 mb-3">Comentarios</h4>
    
    <!-- Formulario (solo para editor/admin) -->
    {% if context.get('module_roles', {}).get('tu_modulo') in ['editor', 'admin'] %}
    <div class="mb-4 border-b pb-4">
        <div class="flex gap-2">
            <textarea name="nuevo_comentario" 
                      id="textarea-comment-{{ id_oportunidad }}"
                      rows="2" 
                      placeholder="Escribe un comentario..."
                      class="flex-1 border-gray-300 rounded-md"></textarea>
            
            <button type="button"
                    hx-post="/tu_modulo/comentarios/{{ id_oportunidad }}"
                    hx-include="#textarea-comment-{{ id_oportunidad }}"
                    hx-target="#comentarios-{{ id_oportunidad }}"
                    hx-swap="innerHTML"
                    hx-on::after-request="document.getElementById('textarea-comment-{{ id_oportunidad }}').value=''"
                    class="bg-blue-600 hover:bg-blue-700 text-white px-3 rounded">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path>
                </svg>
            </button>
        </div>
    </div>
    {% endif %}
    
    <!-- Historial (carga automática) -->
    <div id="comentarios-{{ id_oportunidad }}"
         hx-get="/tu_modulo/partials/comentarios/{{ id_oportunidad }}"
         hx-trigger="load"
         hx-swap="innerHTML">
        <p class="text-gray-400">Cargando...</p>
    </div>
</div>
```

**IMPORTANTE: No anidar formularios**
- Si estás dentro de un `<form>` existente, **NO uses `<form>` para comentarios**
- Usa `<div>` + botón con `hx-post` + `hx-include`

## Sistema de Notificaciones

### Lógica de Destinatarios

**TO (Principal)**:
- Si autor = solicitante → notifica a responsable
- Si autor = responsable → notifica a solicitante
- **No se notifica a uno mismo**

**CC (Copia)**:
- Correos configurados en `tb_config_emails` donde:
  - `trigger_field = 'NUEVO_COMENTARIO'`
  - `modulo = 'GLOBAL'` O `modulo = departamento_slug`

### Configuración en Base de Datos

```sql
-- Ejemplo: Notificar a gerente de simulación en todos los comentarios
INSERT INTO tb_config_emails (modulo, trigger_field, email_to_add)
VALUES ('SIMULACION', 'NUEVO_COMENTARIO', 'gerente.simulacion@enertika.com');

-- Ejemplo: Notificar a dirección en TODOS los módulos
INSERT INTO tb_config_emails (modulo, trigger_field, email_to_add)
VALUES ('GLOBAL', 'NUEVO_COMENTARIO', 'direccion@enertika.com');
```

### Template de Email

**Ubicación**: `templates/shared/emails/workflow/new_comment.html`

**Características**:
- HTML profesional sin emojis
- Colores corporativos Enertika
- Información del proyecto
- Badge de departamento
- Texto del comentario
- Autor y fecha

**Nota**: Actualmente el envío está en modo simulado (logging). Para activar:
1. Descomentar líneas 203-209 en `core/workflow/service.py`
2. Integrar con sistema de tokens Microsoft Graph

## Mejores Prácticas

### 1. Logging para Diagnóstico

```python
import logging

logger = logging.getLogger("TuModulo")

@router.post("/comentarios/{id}")
async def create_comentario(...):
    logger.info(f"[ROUTER] Recibido POST comentario para {id_oportunidad}")
    await workflow_service.add_comentario(...)
    logger.info(f"[ROUTER] Comentario guardado exitosamente")
```

### 2. Manejo de Errores

```python
try:
    await workflow_service.add_comentario(...)
except Exception as e:
    logger.error(f"Error al crear comentario: {e}")
    # Retornar mensaje de error al usuario
    return HTMLResponse("<div class='text-red-600'>Error al guardar comentario</div>")
```

### 3. Permisos Granulares

```python
# Ver comentarios: cualquier rol
_ = require_module_access("tu_modulo")

# Crear comentarios: solo editor/admin
_ = require_module_access("tu_modulo", "editor")
```

### 4. UI Consistente

- Usa siempre el template `shared/partials/comentarios_list.html`
- Mantén el mismo diseño de formulario
- Agrega IDs únicos para evitar conflictos HTMX

## Problemas Comunes y Soluciones

### 1. Comentarios no se guardan

**Síntoma**: No aparece POST en logs, BD vacía

**Causa**: Formularios anidados (HTML inválido)

**Solución**:
```html
<!-- ❌ MAL: form dentro de form -->
<form>
  <form hx-post="/comentarios/...">...</form>
</form>

<!-- BIEN: div + button con hx-post -->
<form>
  <div>
    <textarea id="comment-text"></textarea>
    <button hx-post="/comentarios/..." hx-include="#comment-text">
  </div>
</form>
```

### 2. Error "context is undefined"

**Síntoma**: Jinja2 error en template

**Solución**: Pasar `context` al template
```python
return templates.TemplateResponse("template.html", {
    "request": request,
    "context": context  # <-- AGREGAR
})
```

### 3. Notificaciones no se envían

**Síntoma**: Comentario se guarda pero no llega email

**Diagnóstico**:
```python
# Revisar logs
logger.info(f"[NOTIFICACION] Envio simulado a {recipients}")
```

**Causa**: Sistema en modo simulado (por diseño)

**Activar envío real**:
1. Descomentar líneas 203-209 en `core/workflow/service.py`
2. Asegurar integración con `MicrosoftAuth`

## Tabla: Módulos vs WorkflowService

| Módulo | Departamento Slug | Módulo Origen | Estado |
|--------|------------------|---------------|--------|
| Simulación | `SIMULACION` | `simulacion` | ✅ Implementado |
| Comercial | `COMERCIAL` | `comercial` | ✅ Implementado |
| Ingeniería | `INGENIERIA` | `ingenieria` | ⏳ Pendiente |
| Compras | `COMPRAS` | `compras` | ⏳ Pendiente |
| Proyectos | `PROYECTOS` | `proyectos` | ⏳ Pendiente |

## Checklist de Integración

- [ ] Importar `get_workflow_service` en router
- [ ] Crear endpoint POST `/comentarios/{id}`
- [ ] Crear endpoint GET `/partials/comentarios/{id}`
- [ ] Agregar formulario en template UI
- [ ] Usar template `shared/partials/comentarios_list.html`
- [ ] Configurar permisos `require_module_access`
- [ ] Pasar `context` al template si hay checks de rol
- [ ] Definir `departamento_slug` correcto
- [ ] Definir `modulo_origen` correcto
- [ ] Agregar logging apropiado
- [ ] Configurar destinatarios CC en `tb_config_emails`
- [ ] Probar envío de comentario
- [ ] Verificar historial se actualiza
- [ ] Validar que no hay formularios anidados

---

[← Volver al Índice](README.md)
