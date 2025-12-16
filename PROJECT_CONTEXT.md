# Enertika Ops Core - Contexto Maestro del Proyecto

## 🧠 Instrucciones para la IA (System Prompt Hook)
1. **Estado:** Migración de PowerApps/Automate a Python (FastAPI/HTMX) + Desarrollo de nuevos módulos (Extensión de Proyectos).
2. **Verdad Absoluta:** Este archivo mata cualquier suposición anterior.
3. **Stack:** FastAPI, Jinja2, HTMX, TailwindCSS, Supabase, Microsoft Graph API.
4. **Regla de Oro:** No inventar código. Validar lógica de negocio contra este documento antes de implementar.

---

## 🏢 Definición de Departamentos (Roles)
* **Comercial:** Dueño de la relación con el cliente. Inicia solicitudes.
* **Simulación:** Depto. Independiente. Usa PVsol/Sunwise. Cliente interno: Comercial. **Requiere módulo propio de gestión y reportes.**
* **Ingeniería:** Dimensionamiento técnico y listas de materiales. Responsable principal de Levantamientos.
* **Construcción:** Ejecución e instalación en sitio. También apoya en Levantamientos.
* **O&M:** Post-venta y monitoreo.
* **Compras:** Apoyo transversal. Control de presupuesto y homologación de materiales (Proveedor vs Interno).
* **Dirección:** Gatekeeper (Aprueba paso de Venta a Proyecto).

---

## 🗺️ Mapa de Flujo de Valor (End-to-End)

### Fase 1: Ciclo Comercial & Simulación (Operación)
1. **Solicitud Inicial:** Tipos: **Pre-Oferta** o **Licitación**.
2. **Carga Multisitio:** Archivo Excel con datos de consumos, tarifas y geolocalización.
3. **Guardado & Notificación:** Oportunidad y Sitios se guardan en BD. Se notifica al equipo de Simulación vía correo electrónico (Microsoft Graph).
4. **Simulación:** El equipo de Simulación toma la tarea, la procesa y actualiza los campos de KWp y fechas.

### Fase 2: Módulo de Levantamientos (Nuevo)
- **Concepto:** **"Levantamientos Solicitados"** (Cola de tareas).
- **Notificación de Entrega:** Se notifica a **Simulación** y a **Comercial** (para que solicite Actualización de Oferta).

### Fase 3: La Extensión (Cierre de Venta -> Proyecto)
- **Gate 1 (Dirección):** Genera ID de Proyecto, crea estructura de carpetas en SharePoint y dispara Banderazo (Notificación a todas las áreas).

### Fase 4: Compras (Soporte)
- **Objetivo:** Espejo simplificado de Odoo para tracking de facturas/pagos por proyecto y homologación.

---

## 🟢 Estado de la Infraestructura y Progreso UI (ACTUALIZADO)

| Área | Estado | Observación |
| :--- | :--- | :--- |
| **Conexión a DB** | **✅ ÉXITO TOTAL** | El error de `TimeoutError` ha sido resuelto migrando al **Session Pooler** de Supabase (Puerto 5432 + Host Pooler). La persistencia está activa. |
| **Backend Core** | **✅ COMPLETO** | Lógica de negocio de todos los módulos (Comercial, Simulación, Levantamientos, Proyectos, Compras) definida en *Service Layers*. |
| **UI Base (Layout)**| **✅ COMPLETO** | `templates/base.html` y configuración de *routers* de UI listos para Jinja2/HTMX. |
| **UI Comercial** | **✅ COMPLETO** | Router de UI validado. `templates/comercial/form.html` y `templates/comercial/multisitio_form.html` listos para el flujo de carga. |
| **UI Simulación** | **✅ EN CURSO** | Router de UI (`/simulacion/ui`) validado. Falta la lógica de datos y la vista final (`dashboard.html`). |

---

## 🛠️ Backlog Priorizado (Minucioso)

El foco se centra en implementar las *queries* de la DB y la interfaz de usuario.

### 1. Módulo Simulación (Foco Actual)

| Sub-tarea | Detalle Minucioso | Prioridad |
| :--- | :--- | :--- |
| **1.1 UI Frontend** | Finalizar la vista `templates/simulacion/dashboard.html` (KPIs y estructura de tabla). | ALTA |
| **1.2 Backend (Datos)** | Crear *endpoints* de datos (`/simulacion/data/queue`, `/simulacion/kpis/*`) para devolver fragmentos HTML o JSON/datos puros. | **ALTA** |
| **1.3 Persistencia** | Implementar `SELECT` *queries* en `SimulacionService.get_queue()` para poblar el dashboard. | **ALTA** |

### 2. Módulo Comercial

| Sub-tarea | Detalle Minucioso | Prioridad |
| :--- | :--- | :--- |
| **2.1 Persistencia (CRUD)** | Implementar `INSERT` en `ComercialService.create_oportunidad` (tabla `tb_oportunidades`). | **ALTA** |
| **2.2 Carga Excel** | Implementar la lógica de Pandas y el `executemany` (bulk insert) en `ComercialService.process_multisitio_excel` (tabla `tb_sitios_oportunidad`). | **ALTA** |

### 3. Módulos Levantamientos / Proyectos / Compras

| Sub-tarea | Detalle Minucioso | Prioridad |
| :--- | :--- | :--- |
| **3.1 UI / Routers** | Crear el Router de UI y la vista base para cada módulo restante (`/levantamientos/ui`, `/proyectos/ui`, `/compras/ui`). | Media |
| **3.2 Persistencia** | Implementar las *queries* CRUD en los *Service Layers* respectivos. | Media |

---

### ➡️ Siguiente Acción

Procederemos con el siguiente paso lógico en el *backlog*: **Implementar los Endpoints de Datos de Prueba (Simulación)** para alimentar el *Dashboard*.

**Instrucción:** Ya tienes el contexto actualizado y validado. Vamos a continuar con la implementación del código del Módulo Simulación para generar los datos de la cola de trabajo.