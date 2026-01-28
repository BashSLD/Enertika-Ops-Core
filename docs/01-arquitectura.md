# Arquitectura UI (HTMX + SPA)

> Parte de la [Guía Maestra de Desarrollo - Enertika Ops Core](README.md)
> 
> **Versión:** 2.1  
> **Última Actualización:** 2026-01-14

---

## Concepto Principal

La aplicación funciona como una **SPA (Single Page Application)** usando HTMX para navegación dinámica.

**Contenedor Principal**: `id="main-content"` (definido en `base.html`)

## Reglas de Navegación

### **Navegación Principal (Sidebar/Menús)**

Usar **SIEMPRE**:
```html
hx-get="..." 
hx-target="#main-content" 
hx-swap="innerHTML"
hx-push-url="true"  <!-- OBLIGATORIO -->
```

### **Cuándo usar `hx-push-url="true"`**

Es **OBLIGATORIO** en:

1. Enlaces de la Barra Lateral (Sidebar)
2. Botones de "Nuevo Registro" o "Crear"
3. Botones de "Cancelar" que regresan al Dashboard

**¿Por qué?** Permite que el usuario recargue la página (F5) sin perder su ubicación.

### **Detección Inteligente de Contexto**

En **TODOS** los endpoints `/ui`:

```python
@router.get("/ui", include_in_schema=False)
async def get_modulo_ui(request: Request, context=Depends(get_current_user_context), _=require_module_access("modulo")):
    # Detectar si es navegación HTMX o carga directa
    if request.headers.get("hx-request"):
        template = "modulo/tabs.html"  # Solo contenido interno
    else:
        template = "modulo/dashboard.html"  # Wrapper completo (con base.html)
    
    return templates.TemplateResponse(template, {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role"),
        "module_roles": context.get("module_roles", {}),  # CRÍTICO
        "current_module_role": context.get("module_roles", {}).get("modulo", "viewer")
    })
```

**Explicación**:
- **HTMX request** (desde sidebar): Solo contenido → carga rápida sin duplicar layout
- **Normal request** (F5 o URL directa): Página completa → incluye sidebar, header, etc.

## Estructura de Archivos

```
templates/
  base.html                 ← Layout principal con sidebar
  modulo/
    dashboard.html          ← Wrapper (extiende base.html)
    tabs.html               ← Contenido principal (tabs/cards)
    form.html               ← Formularios
    partials/               ← Componentes reutilizables
      messages/             ← Notificaciones inline
        success.html
        error.html
        warning.html
      toasts/               ← Notificaciones flotantes
        toast_success.html
        toast_error.html
      cards.html
      list.html
```

## Organización de Partials con Subcarpetas

Los partials pueden organizarse en **subcarpetas temáticas** para mejorar la escalabilidad:

### **Estructura Recomendada**

```
templates/
  modulo/
    partials/
      messages/          ← Mensajes inline (contextuales al contenido)
        success.html
        error.html
        warning.html
        info.html
      toasts/            ← Notificaciones flotantes (fixed position)
        toast_success.html
        toast_error.html
      cards/             ← Componentes de tarjetas
        item_card.html
      forms/             ← Formularios reutilizables
        search_form.html
```

### **Diferencia: Messages vs Toasts**

| Tipo | Ubicación | Uso | Ejemplo |
|------|-----------|-----|---------|
| **messages/** | Inline, relativa al contenido | Feedback directo de una acción | Éxito al crear registro |
| **toasts/** | Fixed, top-right | Notificaciones globales | Error de conexión |

### **Templates Genéricos Disponibles**

Ubicados en `_TEMPLATE_partials/` para copiar a nuevos módulos:

- `messages/success.html` - Mensaje de éxito inline
- `messages/error.html` - Mensaje de error inline  
- `messages/warning.html` - Advertencia inline
- `messages/info.html` - Información inline
- `toasts/toast_success.html` - Toast de éxito flotante
- `toasts/toast_error.html` - Toast de error flotante

**Uso en endpoints**:
```python
# Mensaje inline (dentro del contenido)
return templates.TemplateResponse("modulo/partials/messages/success.html", {
    "request": request,
    "title": "¡Operación Exitosa!",
    "message": "El registro fue creado correctamente"
})

# Toast flotante (notificación global)
return templates.TemplateResponse("modulo/partials/toasts/toast_error.html", {
    "request": request,
    "title": "Error de Conexión",
    "message": "No se pudo conectar al servidor"
})
```

**Beneficios**:
- Escalabilidad en módulos grandes
- Fácil localización de componentes
- Reutilización de mensajes estándar
- Consistencia visual en toda la aplicación


## Alpine.js para Interactividad (Opcional)

### **Regla de Oro: ¿Requiere Servidor?**

| Acción | ¿Requiere Datos del Servidor? | Herramienta |
|--------|----------------------------|-------------|
| Expandir/colapsar sección | NO (solo CSS) | **Alpine.js** |
| Tooltip informativo | NO (texto estático) | **Alpine.js** |
| Confirmación visual | NO (diálogo local) | **Alpine.js** |
| Resaltar elemento | NO (solo clase CSS) | **Alpine.js** |
| **Cargar datos nuevos** | SÍ (consulta BD) | **HTMX** |
| **Guardar cambios** | SÍ (modifica BD) | **HTMX** |

### **Casos de Uso Recomendados**

```html
<!-- 1. Expandir/Colapsar con Alpine -->
<div x-data="{ expanded: false }">
    <button @click="expanded = !expanded">
        <svg :class="{ 'rotate-180': expanded }">▼</svg>
    </button>
    <div x-show="expanded" x-transition>
        <!-- Contenido ya presente en DOM -->
    </div>
</div>

<!-- 2. Tooltip Informativo -->
<div x-data="{ show: false }">
    <span @mouseenter="show = true" @mouseleave="show = false">⚠️</span>
    <div x-show="show" x-transition class="tooltip">
        Información adicional
    </div>
</div>

<!-- 3. Confirmación antes de Acción -->
<div x-data="{ confirm: false }">
    <button @click="confirm = true">Eliminar</button>
    <div x-show="confirm" x-transition>
        ¿Seguro?
        <button hx-delete="/api/..." @click="confirm = false">Sí</button>
        <button @click="confirm = false">No</button>
    </div>
</div>

<!-- 4. Resaltado al Seleccionar -->
<div x-data="{ selected: false }" 
     :class="{ 'bg-blue-50 ring-2': selected }"
     @click="selected = !selected">
    Card seleccionable
</div>
```

### **Combinación Alpine + HTMX**

Para acciones que requieren servidor pero con UX mejorada:

```html
<!-- Expandir CON carga de datos (solo primera vez) -->
<div x-data="{ expanded: false }">
    <button @click="expanded = !expanded"
            hx-get="/api/details/{{ id }}"
            hx-trigger="click once"
            hx-target="#details-{{ id }}">
        Ver Detalles
    </button>
    <div x-show="expanded" x-transition id="details-{{ id }}">
        Cargando...
    </div>
</div>
```

---

## Ver También

- [Sistema de Permisos](02-permisos.md) - Control de acceso en UI
- [Crear Módulo](03-crear-modulo.md) - Implementar estructura
- [UI/UX](06-ui-ux.md) - Componentes est ándar
