# 2. Sistema de Permisos

## Jerarquía de Roles

### **Rol de Sistema** (Usuario)

```python
role = context.get("role")  # Valores: "ADMIN", "MANAGER", "USER"
```

- **ADMIN**: Acceso total a TODO (bypasea permisos de módulos)
- **MANAGER**: Rol de confianza. **Solo lectura** por defecto, pero habilita permisos elevados si se combina con rol de módulo "editor".
- **USER**: Usuario estándar, restringido a sus roles de módulo.

### **Roles de Módulo** (Específicos por módulo)

```python
current_module_role = context.get("module_roles", {}).get("comercial", "viewer")
```

Valores posibles:
- **viewer**: Solo lectura (ver datos)
- **editor**: Crear y editar registros
- **assignor**: Asignar tareas/responsables
- **admin**: Control total del módulo

## 1. REGLA CRÍTICA - Rol ADMIN de Sistema

Los usuarios con `role == 'ADMIN'` **SIEMPRE** tienen acceso completo.

**NUNCA** hacer esto:
```python
# INCORRECTO
{% if current_module_role in ['editor', 'assignor', 'admin'] %}
```

**SIEMPRE** hacer esto:
```python
# CORRECTO
{% set can_edit = (role == 'ADMIN') or (current_module_role in ['editor', 'assignor', 'admin']) %}
{% if can_edit %}
```

## 2. REGLA DE ACCESO ELEVADO (Managers)

Para funciones sensibles (Registro Extraordinario, Fechas Manuales), aplicamos una lógica mixta:

> **Acceso Permitido Si:**
> 1. Es `ADMIN` (Sistema)
> 2. Es `admin` (Módulo)
> 3. Es `MANAGER` (Sistema) **Y** tiene rol `editor` (o superior) en el módulo.

```python
# Patrón de Validación en Python
role = context.get("role")
module_role = context.get("module_roles", {}).get("modulo", "")
is_module_editor = module_role in ["editor", "assignor", "admin"]

has_access = (role == "ADMIN") or \
             (module_role == "admin") or \
             (role == "MANAGER" and is_module_editor)
```

## Validación en Backend

**Obligatorio en TODOS los endpoints**:

```python
from core.permissions import require_module_access

# Solo lectura
@router.get("/ui")
async def get_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("modulo"))  # ← OBLIGATORIO
):
    pass

# Requiere editar
@router.get("/form")
async def get_form(
    request: Request,
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("modulo", "editor"))  # ← Nivel mínimo: editor
):
    pass

# Requiere asignar
@router.post("/assign")
async def assign_task(
    request: Request,
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("modulo", "assignor"))
):
    pass

# Requiere admin del módulo
@router.delete("/{id}")
async def delete_item(
    request: Request,
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("modulo", "admin"))
):
    pass
```

**¿Qué hace `require_module_access()`?**
- Valida que el usuario tenga acceso al módulo
- Valida el nivel de permiso requerido
- Retorna **403 Forbidden** automáticamente si no cumple
- Bypasea validación si `role == 'ADMIN'`

## Control de Permisos en UI

### Paso 1: Definir Variables de Permiso

Al inicio del template (después de `{% extends "base.html" %}`):

```html
{% set can_edit = (role == 'ADMIN') or (current_module_role in ['editor', 'assignor', 'admin']) %}
{% set can_assign = (role == 'ADMIN') or (current_module_role in ['assignor', 'admin']) %}
{% set is_admin = (role == 'ADMIN') or (current_module_role == 'admin') %}
```

### Paso 2: Aplicar en Botones

#### **Botón Crear/Nuevo**

```html
{% if can_edit %}
    <!-- BOTÓN ACTIVO -->
    <button hx-get="/finanzas/form" 
            hx-target="#main-content" 
            hx-push-url="true"
            class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded shadow">
        ➕ Nuevo Gasto
    </button>
{% else %}
    <!-- BOTÓN DESHABILITADO CON TOOLTIP -->
    <div class="relative group">
        <button disabled
                class="bg-gray-300 text-gray-500 font-bold py-2 px-4 rounded shadow cursor-not-allowed opacity-50">
            ➕ Nuevo Gasto 🔒
        </button>
        <div class="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
            ⚠️ Solo lectura - Requiere permisos de edición
            <div class="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900"></div>
        </div>
    </div>
{% endif %}
```

#### **Botón Editar (en filas/cards)**

```html
{% if can_edit %}
    <button hx-get="/finanzas/edit/{{ item.id }}" 
            class="text-blue-600 hover:text-blue-800">
        ✏️ Editar
    </button>
{% else %}
    <span class="text-gray-400">✏️ Editar 🔒</span>
{% endif %}
```

---

[← Volver al Índice](README.md)
