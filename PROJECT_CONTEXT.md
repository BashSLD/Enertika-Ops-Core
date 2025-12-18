# Enertika Ops Core - Contexto Maestro del Proyecto

## 🧠 Instrucciones para la IA (System Prompt Hook - ESTRICTO)
1. **ROL INMUTABLE:** Eres un **Desarrollador Backend Python Senior** (FastAPI/Asyncpg). Tu estilo es técnico, directo, franco y orientado a soluciones. **NUNCA** salgas de este rol.
2. **VERDAD ABSOLUTA E INTEGRIDAD:** Este archivo mata cualquier suposición anterior o conocimiento general.
   - **CANDADO DE ARQUITECTURA:** La arquitectura es **Modular Monolith**. Las clases de servicio (`Service`) **VIVEN DENTRO** de `router.py` por diseño.
   - **PROHIBIDO** inventar o asumir la existencia de archivos que no estén en el "Mapa de Archivos" (ej: **NO EXISTE** `services.py`, `models.py` o `controllers.py` separados).
   - **PROHIBIDO** refactorizar la estructura de carpetas sin autorización expresa. Respetar la arquitectura existente es la prioridad #1.
3. **Stack Tecnológico:** FastAPI, Jinja2 (SSR), HTMX (Interactividad), TailwindCSS, Supabase (Postgres Session Pooler), Microsoft Graph API.
4. **UI Diseño:** Priorizar configuración corporativa ENERTIKA. Textos de navegación simplificados (ej: "Comercial").

# --- CONFIGURACIÓN DE ESTILO CORPORATIVO (ENERTIKA) ---
ESTILO = {
    "primary": "#123456",        # Azul Oscuro Corporativo
    "accent": "#00BABB",         # Turquesa
    "dark_grey": "#262626",      # Texto principal
    "light_grey": "#dfddd9",     # Fondos suaves
    "white": "#FFFFFF",
}
# ----------------------------------------------------

---

## 📂 Mapa de Archivos y Ubicación de Clases (CRÍTICO)

### 1. Núcleo (Core)
*Infraestructura transversal compartida.*
* **`main.py`**: Entry point (`app`). Configuración de Jinja2, StaticFiles y registro de Routers.
* **`core/config.py`**: Clase `Settings`. Variables `.env`, URL DB (Pooler) y Credenciales MS Graph.
* **`core/database.py`**: Función `get_db_connection`. Gestión del pool `asyncpg`.
* **`core/microsoft.py`**: Clase `MicrosoftAuth`. Singleton para OAuth2 y Graph API.

### 2. Módulos de Negocio (/modules)
*Cada carpeta encapsula la lógica. **Service y Router conviven en el mismo archivo**.*

* **Módulo Comercial (`modules/comercial/`)**
    * `router.py`: Contiene `APIRouter` **Y** `class ComercialService`.
        * *Métodos:* `create_oportunidad`, `process_multisitio_excel` (Pendiente), `send_simulacion_email`.
    * `schemas.py`: `OportunidadCreate`, `SitioOportunidadBase`.

* **Módulo Simulación (`modules/simulacion/`)**
    * `router.py`: Contiene `APIRouter` **Y** `class SimulacionService`.
        * *Métodos:* `get_queue` (Cola de trabajo), asignación técnicos.
    * `schemas.py`: `SimulacionUpdate`.

* **Módulos Levantamientos / Proyectos / Compras**
    * Estructura idéntica: `router.py` (con Service Class interna) + `schemas.py`.

### 3. Interfaz de Usuario (/templates)
*Renderizado Server-Side con Jinja2 + HTMX.*
* **`/templates/base.html`**: Layout principal (Sidebar + Contenedor Dinámico `main-content`).
* **`/templates/comercial/`**: `form.html`, `multisitio_form.html`, `error_message.html`.
* **`/templates/simulacion/`**: `dashboard.html` (KPIs y Tabla).

---

## 🗺️ Reglas de Negocio y Flujo de Valor (Extracto PDF)

### Fase 1: Ciclo Comercial & Simulación (Operación)
1. **Solicitud Inicial:**
   - **ID Estándar:** `OP-YYMMDDhhmm...` (Generado en Backend).
   - **Asunto Correo (Threading):** El sistema debe generar asuntos estandarizados (ej: `PRE OFERTA_CLIENTE_PROYECTO`) para que Graph API pueda encontrar el hilo posteriormente.
   - **Multisitio:** Soportar carga masiva vía Excel.
2. **Simulación (Gestión):**
   - **Status:** Pendiente -> En Revisión -> En Proceso -> Entregado / Cancelado / Perdido.
   - **Cancelación:** Requiere motivo obligatorio y confirmación.
   - **KPIs (Regla de Oro):** Fecha Entrega vs Deadline.
     - *Fórmula:* Si `Fecha Entrega` <= (`Deadline` o `NewDeadline`), entonces "A tiempo", sino "Tarde".
   - **Dato Crítico:** Al cambiar a "Entregado", es **OBLIGATORIO** capturar la **Potencia Simulada (KWp)**. Sin esto, no hay reportes.

### Fase 2: Levantamientos (Cola de Trabajo)
- Comercial solicita "Levantamiento" desde la App.
- Se notifica a Ingeniería/Construcción.
- Al terminar, se notifica a Simulación (ajustar modelo) y Comercial (ajustar oferta).

### Fase 3: Proyectos (La Extensión)
- **Gate 1 (Dirección):** Aprueba "Cierre de Venta" -> Genera ID Proyecto -> Crea Carpetas SharePoint -> Dispara Banderazo.
- **Gate 2, 3, 4:** Traspasos entre Ingeniería -> Construcción -> O&M.

---

## 🟢 Estado Actual del Sistema (Snapshot Técnico)

| Componente | Estado | Detalle Técnico |
| :--- | :--- | :--- |
| **Conexión DB** | **✅ OK** | Solucionado vía Supabase Session Pooler (Puerto 6543). `asyncpg` operativo. |
| **UI Base** | **✅ OK** | `main.py` corregido para cargar `base.html`. Navegación funciona. |
| **Comercial Backend** | **🚧 EN PROCESO** | `create_oportunidad` (Header) listo. Falta lógica de Excel. |
| **Comercial UI** | **✅ OK** | Formulario Paso 1 y Paso 2 conectados vía HTMX. |
| **Simulación** | **⏳ PENDIENTE** | Estructura de archivos creada. Falta lógica de negocio. |

---

## 🛠️ Backlog Priorizado (Siguientes Pasos)

**FOCO ACTUAL: Completar Persistencia Comercial.**

### 1. Módulo Comercial (Prioridad Máxima)
* **1.1 Carga Excel (`process_multisitio_excel`):**
    * **Ubicación:** `modules/comercial/router.py` -> `class ComercialService`.
    * **Lógica:**
        1. Leer `UploadFile` (bytes) usando `pandas` y `io.BytesIO`.
        2. Validar columnas mandatorias (ej: 'NOMBRE', 'DIRECCION', 'TARIFA', 'CONSUMO').
        3. Convertir DataFrame a lista de diccionarios/tuplas.
        4. Ejecutar `await conn.executemany(...)` hacia `tb_sitios_oportunidad`.
* **1.2 Envío Graph API:** Implementar `send_simulacion_email` usando la clase `MicrosoftAuth`.

### 2. Módulo Simulación
* **2.1 Dashboard UI:** Poblar `dashboard.html` con datos reales.
* **2.2 Endpoints Data:** `/simulacion/data/queue` (Cola de trabajo) y KPIs.