# 3. Crear Nuevo Módulo - Paso a Paso

## Checklist Completo

### **Paso 1: Copiar Template del Router**

```bash
# Ejemplo para módulo "finanzas"
cp modules/_TEMPLATE_router.py modules/finanzas/router.py
```

### **Paso 2: Personalizar Router**

Abrir `modules/finanzas/router.py` y reemplazar:

| Buscar | Reemplazar |
|--------|------------|
| `TEMPLATE` | `finanzas` |
| `"TEMPLATE"` | `"finanzas"` |
| `/TEMPLATE` | `/finanzas` |
| `Módulo TEMPLATE` | `Módulo Finanzas` |

**Ejemplo**:
```python
# ANTES
router = APIRouter(
    prefix="/TEMPLATE",
    tags=["Módulo TEMPLATE"],
)

@router.get("/ui")
async def get_template_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("TEMPLATE"))
):
    return templates.TemplateResponse("TEMPLATE/dashboard.html", {...})

# DESPUÉS
router = APIRouter(
    prefix="/finanzas",
    tags=["Módulo Finanzas"],
)

@router.get("/ui")
async def get_finanzas_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("finanzas"))
):
    return templates.TemplateResponse("finanzas/dashboard.html", {...})
```

### **Paso 3: Copiar Template HTML**

```bash
# Crear directorio del módulo
mkdir templates/finanzas

# Copiar dashboard base
cp templates/_TEMPLATE_dashboard.html templates/finanzas/dashboard.html
```

**Personalizar `dashboard.html`**:
```html
{% extends "base.html" %}

{% block title %}Enertika Ops Core | Finanzas{% endblock %}

{% block content %}
<div class="container mx-auto">
    <div class="bg-white rounded-lg shadow-lg p-6">
        <h1 class="text-3xl font-bold text-gray-800 mb-4">
            Módulo Finanzas
        </h1>
        
        <!-- Contenido específico del módulo -->
    </div>
</div>
{% endblock %}
```

### **Paso 4: Registrar en `main.py`**

```python
# En main.py, agregar:
from modules.finanzas import router as finanzas_router
app.include_router(finanzas_router.router)
```

### **Paso 5: Agregar a Base de Datos**

El módulo ya debe estar en `tb_modulos_catalogo`. Si no existe:

```sql
INSERT INTO tb_modulos_catalogo (nombre, slug, ruta, icono, orden, is_active)
VALUES ('Finanzas', 'finanzas', '/finanzas/ui', 'fa fa-money', 50, true);
```

**Campos**:
- `nombre`: Nombre visible en UI
- `slug`: Identificador único (minúsculas, sin espacios)
- `ruta`: URL del endpoint `/ui`
- `icono`: Emoji o clase de ícono
- `orden`: Posición en el sidebar
- `is_active`: Si se muestra o no

### **Paso 6: Verificar Permisos**

Desde el módulo **Admin** (`/admin/ui`):
1. Ir a "Gestión de Permisos"
2. Asignar permisos a usuarios para el nuevo módulo
3. Verificar que aparece desbloqueado en el sidebar

---

[← Volver al Índice](README.md)
