# 4. Service Layer Pattern

## Regla de Oro

> **TODA la lógica de negocio DEBE estar en `service.py`**  
> **El `router.py` SOLO orquesta HTTP y delega al service**

## Estructura de Módulo (OBLIGATORIA)

**REGLA CRÍTICA**: Todos los nuevos módulos **DEBEN** usar esta estructura con `service.py` separado.

```
modules/
  nombre_modulo/
    __init__.py           ← Exporta router
    router.py             ← SOLO endpoints HTTP (rutas)
    service.py            ← OBLIGATORIO: Lógica de negocio
    schemas.py            ← Modelos Pydantic (opcional)
```

**Distribución de Responsabilidades**:

| Archivo | Responsabilidad | Contiene |
|---------|----------------|----------|
| `router.py` | Capa HTTP | Endpoints, validación de requests, responses |
| `service.py` | Lógica de negocio | Cálculos, validaciones, queries, reglas de negocio |
| `schemas.py` | Modelos de datos | Pydantic models para validación |

## Responsabilidades Claras

### **`service.py` (Lógica de Negocio)**
- Validaciones de negocio
- Cálculos y transformaciones
- Queries complejos a BD
- Generación de timestamps
- Integración con APIs externas
- Procesamiento de datos

### **`router.py` (Orquestación HTTP)**
- Recibir request HTTP
- Validar autenticación/permisos
- Parsear Form/JSON
- Llamar al service
- Retornar response (template/JSON)

## Implementación

### **1. Archivo `service.py` (Completo)**

```python
# modules/finanzas/service.py
from datetime import datetime
from uuid import UUID
from typing import List
import logging
from fastapi import HTTPException

logger = logging.getLogger("FinanzasModule")

class FinanzasService:
    """Maneja toda la lógica de negocio del módulo Finanzas."""
    
    @staticmethod
    def calcular_impuesto(monto: float) -> float:
        """Cálculo de impuestos (regla de negocio)."""
        return monto * 0.16
    
    async def get_gastos(self, conn, user_context: dict, filtros: dict = None):
        """Obtiene gastos con filtros y permisos aplicados."""
        user_id = user_context.get("user_db_id")
        role = user_context.get("role")
        
        query = "SELECT * FROM tb_gastos WHERE 1=1"
        params = []
        
        # Filtro de seguridad
        if role not in ['ADMIN', 'MANAGER']:
            query += " AND creado_por_id = $1"
            params.append(user_id)
        
        # Filtros adicionales
        if filtros and filtros.get('fecha_inicio'):
            query += f" AND fecha >= ${len(params) + 1}"
            params.append(filtros['fecha_inicio'])
        
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]
    
    async def create_gasto(self, conn, datos: dict, user_id: UUID) -> UUID:
        """Crea un nuevo gasto con validaciones de negocio."""
        # Validación de negocio
        if datos['monto'] <= 0:
            raise HTTPException(status_code=400, detail="El monto debe ser positivo")
        
        # Calcular impuesto
        impuesto = self.calcular_impuesto(datos['monto'])
        total = datos['monto'] + impuesto
        
        # Insertar en BD
        query = """
            INSERT INTO tb_gastos (monto, impuesto, total, creado_por_id, descripcion)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id_gasto
        """
        gasto_id = await conn.fetchval(query, datos['monto'], impuesto, total, user_id, datos['descripcion'])
        return gasto_id

# Helper para inyección de dependencias
def get_finanzas_service():
    return FinanzasService()
```

### **2. Archivo `router.py` (Simplificado)**

```python
# modules/finanzas/router.py
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from core.database import get_db_connection
from core.security import get_current_user_context
from core.permissions import require_module_access
from .service import FinanzasService, get_finanzas_service  # ← IMPORTAR SERVICE

templates = Jinja2Templates(directory="templates")

router = APIRouter(prefix="/finanzas", tags=["Finanzas"])

@router.get("/ui")
async def get_ui(
    request: Request,
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("finanzas"))
):
    """Muestra el dashboard principal."""
    return templates.TemplateResponse("finanzas/dashboard.html", {
        "request": request,
        "user_name": context.get("user_name"),
        "role": context.get("role")
    })

@router.get("/list")
async def get_gastos_list(
    request: Request,
    service: FinanzasService = Depends(get_finanzas_service),  # ← INYECTAR SERVICE
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("finanzas"))
):
    """Endpoint simplificado - delega al servicio."""
    gastos = await service.get_gastos(conn, context, {})  # ← USAR SERVICE
    
    return templates.TemplateResponse("finanzas/partials/list.html", {
        "request": request,
        "gastos": gastos
    })

@router.post("/create")
async def create_gasto(
    request: Request,
    monto: float = Form(...),
    descripcion: str = Form(...),
    service: FinanzasService = Depends(get_finanzas_service),
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context),
    _ = Depends(require_module_access("finanzas", "editor"))
):
    """Crea un gasto."""
    datos = {"monto": monto, "descripcion": descripcion}
    gasto_id = await service.create_gasto(conn, datos, context['user_db_id'])  # ← USAR SERVICE
    
    return templates.TemplateResponse("finanzas/partials/messages/success.html", {
        "request": request,
        "title": "¡Gasto Creado!",
        "message": f"Gasto #{gasto_id} registrado correctamente"
    })
```

## Manejo de Timestamps (CRÍTICO)

**NUNCA usar `datetime.now()` directamente en router.py**

**SIEMPRE delegar al service.py con zona horaria**

### Implementación Estándar

```python
# service.py
from datetime import datetime
from zoneinfo import ZoneInfo  # Nativo Python 3.9+

class MiModuloService:
    
    def get_current_datetime_mx(self) -> datetime:
        """
        Obtiene hora actual en México (America/Mexico_City).
        
        Esta función es la fuente de verdad para todos los timestamps.
        PostgreSQL acepta timezone-aware datetime directamente.
        """
        zona_mx = ZoneInfo("America/Mexico_City")
        return datetime.now(zona_mx)
    
    async def crear_registro(self, conn, datos: dict, user_id: UUID):
        # CORRECTO - Usar método del service
        fecha_creacion = self.get_current_datetime_mx()
        
        query = """
            INSERT INTO mi_tabla (id, datos, fecha_creacion)
            VALUES ($1, $2, $3)
        """
        await conn.execute(query, uuid4(), datos, fecha_creacion)
```

```python
# router.py
@router.post("/create")
async def create_item(
    request: Request,
    service: MiModuloService = Depends(get_service),
    conn = Depends(get_db_connection)
):
    # INCORRECTO
    # now = datetime.now()  # NO HACER ESTO
    
    # CORRECTO - Delegar al service
    resultado = await service.crear_registro(conn, datos, user_id)
    return Response(...)
```

## Catálogos Dinámicos en Formularios

**Problema**: Hardcodear opciones de `<select>` en templates hace que los cambios requieran modificar código.

**Solución**: Poblar options dinámicamente desde la base de datos usando catálogos.

### Paso 1: Método en Service Layer

```python
# modules/modulo/service.py
class ModuloService:
    async def get_catalogos_ui(self, conn) -> dict:
        """Obtiene catálogos necesarios para el formulario."""
        tecnologias = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_tecnologias WHERE activo = true ORDER BY nombre"
        )
        tipos_solicitud = await conn.fetch(
            "SELECT id, nombre FROM tb_cat_tipos_solicitud WHERE activo = true ORDER BY nombre"
        )
        
        return {
            "tecnologias": [dict(t) for t in tecnologias],
            "tipos_solicitud": [dict(t) for t in tipos_solicitud]
        }
```

### Paso 2: Endpoint GET del Formulario

```python
# modules/modulo/router.py
@router.get("/form", include_in_schema=False)
async def get_form(
    request: Request,
    context = Depends(get_current_user_context),
    conn = Depends(get_db_connection),
    service: ModuloService = Depends(get_service),
    _ = Depends(require_module_access("modulo", "editor"))
):
    """Muestra el formulario con catálogos dinámicos."""
    
    # Obtener catálogos desde el service
    catalogos = await service.get_catalogos_ui(conn)
    
    return templates.TemplateResponse("modulo/form.html", {
        "request": request,
        "catalogos": catalogos  # Pasar al template
    })
```

### Paso 3: Template con Jinja2 Loop

```html
<!-- templates/modulo/form.html -->
<div>
    <label>Tecnología *</label>
    <div class="relative">
        <select name="id_tecnologia" required
            class="shadow border rounded w-full py-2 px-3 focus:ring-2 focus:ring-[#00BABB]">
            <option value="" disabled selected>Seleccione una tecnología...</option>
            
            {% for tec in catalogos.tecnologias %}
                <option value="{{ tec.id }}">{{ tec.nombre }}</option>
            {% endfor %}
            
        </select>
        <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2">
            <svg class="fill-current h-4 w-4" viewBox="0 0 20 20">
                <path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/>
            </svg>
        </div>
    </div>
</div>
```

### Paso 4: Endpoint POST (Recibir IDs)

```python
@router.post("/form")
async def handle_creation(
    request: Request,
    nombre: str = Form(...),
    id_tecnologia: int = Form(...),  # ← Recibe ID (int), no string
    id_tipo_solicitud: int = Form(...),  # ← Recibe ID (int), no string
    conn = Depends(get_db_connection),
    context = Depends(get_current_user_context)
):
    """Procesa el formulario usando IDs de catálogos."""
    
    # Guardar con FK a catálogos
    query = """
        INSERT INTO tb_registros (
            nombre, id_tecnologia, id_tipo_solicitud, creado_por_id
        ) VALUES ($1, $2, $3, $4)
    """
    await conn.execute(query, nombre, id_tecnologia, id_tipo_solicitud, context['user_db_id'])
    
    # Retornar partial de éxito
    return templates.TemplateResponse("modulo/partials/messages/success.html", {
        "request": request,
        "title": "¡Registro Creado!",
        "message": "El registro fue guardado correctamente"
    })
```

**Regla de Oro**: Si un campo puede tener un **conjunto finito de valores** (tecnología, estado, prioridad, etc.), usa un catálogo con FK.

## Checklist de Validación Service Layer

Antes de hacer commit, verificar:

- [ ] `router.py` NO tiene lógica de negocio
- [ ] `router.py` NO usa `datetime.now()` directamente
- [ ] `service.py` tiene método `get_current_datetime_mx()`
- [ ] Todos los cálculos están en `service.py`
- [ ] Router solo orquesta y delega
- [ ] Service es testeable independientemente

## Beneficios Clave

| Beneficio | Explicación | Ejemplo |
|-----------|-------------|---------|
| **Reutilización** | Usa métodos del service desde otros módulos | `from modules.finanzas.service import FinanzasService` |
| **Testing** | Test directo sin mockear FastAPI | `assert service.calcular_impuesto(100) == 16` |
| **Mantenibilidad** | Cambios de negocio no afectan rutas HTTP | Cambiar fórmula de impuesto = solo editar `service.py` |
| **Legibilidad** | Archivos más cortos y enfocados | Router: 400 líneas vs antes: 1200 líneas |
| **SRP** | Cada archivo una responsabilidad | Router = HTTP, Service = Negocio |

---

[← Volver al Índice](README.md)
