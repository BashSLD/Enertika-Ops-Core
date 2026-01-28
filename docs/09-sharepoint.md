# 9. Integración con SharePoint

## Propósito

Sistema centralizado para gestionar la carga y organización de archivos en SharePoint, garantizando:
- **Upload Robusto** usando Tokens de Aplicación (Service Principal) para evitar problemas de permisos de usuario.
- **Estructura Organizada** mediante configuración base + slugs de origen.
- **Integridad de Datos** usando catálogos (`tb_cat_origenes_adjuntos`).
- **Nombres Únicos** para evitar colisiones.

---

## Arquitectura de Implementación

### 1. Autenticación (Service Principal vs Delegated)

Para garantizar que los archivos siempre se puedan subir independientemente de los permisos individuales del usuario en la carpeta raíz, utilizamos **Tokens de Aplicación**.

*   **Subida de Archivos (Sistema):** Usa `ms_auth.get_application_token()`. La aplicación escribe en la carpeta, no el usuario.
*   **Lectura/Navegación (Usuario):** Puede usar `get_valid_graph_token()` si se requiere contexto de usuario (delegado).

```python
# Ejemplo en service.py
from core.microsoft import get_ms_auth

# 1. Obtener Token de Aplicación (Permiso Files.ReadWrite.All en Azure App)
ms_auth = get_ms_auth()
app_token = ms_auth.get_application_token()

# 2. Inicializar Servicio
sharepoint = SharePointService(access_token=app_token)
```

### 2. Estructura de Carpetas

La ruta física se construye dinámicamente combinando una **Configuración Global** y un **Slug de Origen**.

**Fórmula:**
`{SHAREPOINT_BASE_FOLDER} / {origen_slug} / {ID_Referencia} / {Timestamp}_{Archivo}`

**Componentes:**
1.  **`SHAREPOINT_BASE_FOLDER`**: Configurable en `tb_configuracion_global` (Ej: `APP_ENERTIKA_OPS_CORE`). Permite mover toda la raíz del sistema fácilmente.
2.  **`origen_slug`**: Definido en el código y validado en `tb_cat_origenes_adjuntos` (Ej: `comentario`, `cotizacion`, `evidencia`).
3.  **`ID_Referencia`**: ID Estándar de la Oportunidad o Proyecto (Ej: `OP-20240115-001`).

**Ejemplo Resultante:**
`APP_ENERTIKA_OPS_CORE/comentario/OP-20240115-001/1705349821_Reporte.pdf`

---

## Esquema de Base de Datos

El sistema utiliza dos tablas principales para gestionar los adjuntos:

### 1. Catálogo de Orígenes (`tb_cat_origenes_adjuntos`)
Define los "tipos" permitidos de adjuntos y actúa como Enum.
- `slug` (PK): Identificador único (ej: 'comentario').
- `descripcion`: Uso previsto.

### 2. Registro de Archivos (`tb_documentos_attachments`)
Guarda la referencia del archivo subido.

```sql
INSERT INTO tb_documentos_attachments (
    id_documento,
    nombre_archivo,
    url_sharepoint,
    drive_item_id,
    tamano_bytes,
    origen_slug,     -- FK a tb_cat_origenes_adjuntos
    id_oportunidad,  -- FK opcional
    id_comentario,   -- FK opcional
    subido_por_id,
    fecha_subida
) VALUES (...)
```

---

## Mejores Prácticas Implementadas

### 1. Nombres de Archivo Únicos
Para evitar errores `409 Conflict` en SharePoint o sobrescrituras accidentales, **siempre** anteponemos un timestamp al nombre del archivo antes de subirlo.

```python
import time
timestamp = int(time.time())
filename = f"{timestamp}_{original_filename}"
# 1705349821_revisión_final.pdf
```

### 2. Validación de Tamaño Sincrona
Debido a limitaciones en wrappers asíncronos (`UploadFile`), usamos el acceso al archivo subyacente para validar tamaño de forma segura:

```python
file.file.seek(0, 2)  # Ir al final
size = file.file.tell() # Leer posición
file.file.seek(0)     # Volver al inicio
```

### 3. Configuración Centralizada
Nunca hardcodear la carpeta raíz. Siempre leerla de `tb_configuracion_global`.

```python
config = await conn.fetchrow("SELECT valor FROM tb_configuracion_global WHERE clave = 'SHAREPOINT_BASE_FOLDER'")
base_folder = config['valor'] # Ej: "APP_PROD_V1"
```

---

## Checklist para Nuevos Módulos

Si vas a agregar adjuntos a un nuevo módulo:

1.  [ ] Agregar el nuevo slug a `tb_cat_origenes_adjuntos` (ej: `ingenieria_plano`).
2.  [ ] En tu `service.py`, leer `SHAREPOINT_BASE_FOLDER`.
3.  [ ] Construir la ruta usando el slug: `{base}/{slug}/{id}`.
4.  [ ] Usar `ms_auth.get_application_token()` para la subida.
5.  [ ] Guardar el registro en `tb_documentos_attachments` linkeado a tu entidad.
