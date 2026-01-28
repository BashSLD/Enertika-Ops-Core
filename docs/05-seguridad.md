# 5. Seguridad y Sesión

## Arquitectura de Tokens (Base de Datos)

**CAMBIO CRÍTICO**: Los tokens de Microsoft **YA NO se guardan en cookies de sesión**.

**Razón**: Los tokens de Microsoft son demasiado grandes (~2-3KB cada uno), causando que las cookies excedan el límite de 4KB del navegador.

### Nueva Arquitectura

| Dato | Ubicación | Propósito |
|------|-----------|-----------|
| `access_token` | **Base de Datos** (`tb_usuarios.access_token`) | Token activo de Microsoft Graph |
| `refresh_token` | **Base de Datos** (`tb_usuarios.refresh_token`) | Token de renovación de larga duración |
| `token_expires_at` | **Base de Datos** (`tb_usuarios.token_expires_at`) | Timestamp Unix de expiración |
| `user_email` | **Cookie de sesión** | Identificador ligero del usuario |
| `user_name` | **Cookie de sesión** | Nombre del usuario |

## Token Inteligente (Renovación Automática desde BD)

**REGLA CRÍTICA**: **NUNCA** uses `request.session.get("access_token")`.

**SIEMPRE** usa `get_valid_graph_token()` para acciones que requieran Microsoft Graph API.

### Patrón Correcto para Graph API

```python
from core.security import get_valid_graph_token

@router.post("/enviar-correo")
async def enviar(request: Request):
    # 1. Obtener token seguro (lee de BD y renueva automáticamente)
    token = await get_valid_graph_token(request)
    
    # 2. Validar sesión
    if not token:
        from fastapi import Response
        # Redirigir al login preservando el contexto HTMX
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    
    # 3. Usar token
    ms_auth.send_email(token, ...)
```

**Ejemplo con DELETE (Cancelar/Eliminar):**

```python
@router.delete("/{id_oportunidad}", response_class=HTMLResponse)
async def cancelar_oportunidad(
    request: Request,
    id_oportunidad: UUID,
    conn = Depends(get_db_connection)
):
    """Elimina borrador y redirige al dashboard."""
    
    # 1. Validación de sesión con token inteligente
    access_token = await get_valid_graph_token(request)
    if not access_token:
        # Token expirado y no se pudo renovar
        from fastapi import Response
        return Response(status_code=200, headers={"HX-Redirect": "/auth/login?expired=1"})
    
    # 2. Realizar eliminación
    await conn.execute("DELETE FROM tb_oportunidades WHERE id_oportunidad = $1", id_oportunidad)
    
    # 3. Redirigir con HTMX
    from fastapi import Response
    return Response(status_code=200, headers={"HX-Redirect": "/modulo/ui"})
```

**¿Qué hace `get_valid_graph_token()`?**
- Lee `user_email` de la cookie ligera
- Consulta los tokens desde `tb_usuarios` en la BD
- Verifica si el token actual sigue vigente
- Si expira en menos de 5 minutos → **Renueva automáticamente**
- Actualiza la BD con el nuevo token
- Retorna `None` si ambos tokens (access + refresh) expiraron
- **Transparente para el usuario** - No ve errores mientras trabaja

### Validación de Sesión Básica (Vistas)

Para endpoints que **NO** usan Graph API (solo ver datos de BD):

```python
@router.get("/form")
async def get_form(
    request: Request, 
    context = Depends(get_current_user_context)
):
    # Validación simple de sesión
    if not context.get("email"):
        return HTMLResponse(status_code=401)  # ← Trigger modal login
    
    # Continuar con lógica normal...
```

**¿Por qué retornar 401?**
- El frontend (`base.html`) tiene un "Vigilante" que intercepta **401**
- Muestra un **Modal de Reconexión** automático
- **NO** pierde los datos del formulario que el usuario estaba llenando

### NUNCA Hacer Esto

```python
# PROHIBIDO - Las cookies ya NO contienen tokens
access_token = request.session.get("access_token")
ms_auth.send_email(access_token, ...)
```

## Middleware de Sesión

**Configuración Global** (`main.py`):
```python
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.SECRET_KEY,
    max_age=86400,  # 24 horas
    same_site="lax",  # Permite cookies en redirects
    https_only=False  # True en producción con HTTPS
)
```

**Datos Guardados en Sesión (Solo ligeros)**:
- `user_email` - Email del usuario (identificador)
- `user_name` - Nombre del usuario

**Datos Guardados en Base de Datos (Pesados)**:
- `access_token` - Token de acceso actual (expira en 1 hora)
- `refresh_token` - Token de renovación (expira en 90 días)
- `token_expires_at` - Timestamp Unix de cuándo expira el token
- `ultimo_login` - Fecha del último login exitoso

## Integridad de Datos y Concurrencia

### Prevenir Race Conditions con Upsert Atómico

**MAL - Race Condition Posible:**
```python
async def get_or_create_cliente(self, conn, nombre: str):
    # 1. Buscar
    cliente = await conn.fetchrow("SELECT id FROM tb_clientes WHERE nombre_fiscal = $1", nombre)
    if cliente:
        return cliente['id']
    # 2. Insertar - WINDOW de race condition aquí
    new_id = uuid4()
    await conn.execute("INSERT INTO tb_clientes (id, nombre_fiscal) VALUES ($1, $2)", new_id, nombre)
    return new_id
```

**BIEN - Upsert Atómico:**
```python
async def get_or_create_cliente(self, conn, nombre: str):
    nombre_clean = nombre.strip().upper()
    
    # Upsert atómico con ON CONFLICT
    # REQUISITO: UNIQUE CONSTRAINT en tb_clientes(nombre_fiscal)
    query_insert = """
        INSERT INTO tb_clientes (id, nombre_fiscal) 
        VALUES ($1, $2) 
        ON CONFLICT (nombre_fiscal) DO NOTHING
    """
    new_id = uuid4()
    await conn.execute(query_insert, new_id, nombre_clean)
    
    # Recuperar ID (sea nuevo o existente)
    row = await conn.fetchrow("SELECT id FROM tb_clientes WHERE nombre_fiscal = $1", nombre_clean)
    return row['id']
```

**Beneficios:**
- Sin race conditions
- Thread-safe
- Garantiza integridad de datos

## Seguridad y Prevención de Ataques

### Prevención de DoS por Archivos Gigantes

**MAL - Vulnerable a DoS:**
```python
@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # Lee TODO el archivo en RAM sin validar tamaño
    contents = await file.read()  # 2GB → crash del servidor
    # Procesar...
```

**BIEN - Validación de Tamaño:**
```python
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # 1. Resetear puntero
    await file.seek(0)
    
    # 2. Validar tamaño SIN cargar en RAM
    file.file.seek(0, 2)  # Ir al final
    file_size = file.file.tell()  # Obtener tamaño
    await file.seek(0)  # Volver al inicio - CRÍTICO
    
    # 3. Validar ANTES de leer
    if file_size > MAX_FILE_SIZE:
        return templates.TemplateResponse("partials/toasts/toast_error.html", {
            "request": request,
            "title": "Archivo muy grande",
            "message": "El archivo excede el tamaño máximo de 10MB."
        })
    
    # 4. Ahora sí es seguro leer
    contents = await file.read()
```

**Beneficios:**
- Previene crash por memoria
- Usuario recibe feedback inmediato
- Protege estabilidad del servidor

### Eliminar Valores Hardcodeados (Backdoors)

**MAL - Email Hardcodeado:**
```python
@router.get("/debug/set-dept")
async def debug_set_department(request: Request, dept: str = ""):
    user_email = request.session.get("user_email", "")
    if user_email != "sistemas@enertika.mx":  # ⚠️ Backdoor hardcodeada
        raise HTTPException(status_code=403)
```

**BIEN - Validación por Rol:**
```python
@router.get("/debug/set-dept")
async def debug_set_department(
    request: Request, 
    dept: str = "",
    context = Depends(get_current_user_context)
):
    # Validar por ROL de base de datos
    if context.get("role") not in ['ADMIN', 'MANAGER']:
        raise HTTPException(status_code=403)
```

**Beneficios:**
- Sin backdoors en código
- Roles gestionados centralmente
- Facilita auditorías
- Múltiples admins sin cambios de código

### Lógica de Permisos Positiva (Whitelist)

** MAL - Blacklist (Insegura):**
```python
# Si creas un nuevo rol "AUDITOR", verá TODO por defecto
if role != 'MANAGER' and role != 'ADMIN':
    query += " AND creado_por_id = $1"  # Solo ve lo suyo
```

**BIEN - Whitelist (Segura):**
```python
# Principio de "menor privilegio": nuevos roles restringidos por defecto
roles_sin_restriccion = ['MANAGER', 'ADMIN', 'DIRECTOR']

if role not in roles_sin_restriccion:
    query += " AND creado_por_id = $1"  # Solo ve lo suyo
```

**Beneficios:**
- Seguro por defecto
- Nuevos roles automáticamente restringidos
- Escalable y mantenible

### Manejo de Excepciones Específico

** MAL - Catch-all Genérico:**
```python
try:
    cliente_id = await conn.fetchval(query, datos_form['nombre_cliente'])
except Exception as e:  #  Oculta errores de programación
    logger.exception(f"Error: {e}")
    raise HTTPException(status_code=500, detail=f"Error BD: {e}")
```

** BIEN - Excepciones Específicas:**
```python
import asyncpg

try:
    cliente_id = await conn.fetchval(query, datos_form['nombre_cliente'])

except KeyError as e:
    # Error de desarrollo: campo faltante
    logger.error(f"Datos faltantes: {e}")
    raise HTTPException(status_code=400, detail=f"Falta campo requerido: {e}")

except asyncpg.PostgresError as e:
    # Error real de base de datos
    logger.exception(f"Error BD crítico: {e}")
    raise HTTPException(status_code=500, detail="Error de base de datos.")

except Exception as e:
    # Catch-all final para errores inesperados
    logger.exception(f"Error desconocido: {e}")
    raise HTTPException(status_code=500, detail="Error interno.")
```

**Beneficios:**
- Debugging más fácil
- Mensajes apropiados por tipo
- Status codes HTTP correctos
- Bugs detectables inmediatamente

---

[← Volver al Índice](README.md)
