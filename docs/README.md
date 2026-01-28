# Guía Maestra de Desarrollo - Enertika Ops Core

> **Versión:** 2.2 (Optimizada)  
> **Fecha:** 2026-01-17  
---

## Propósito

Documentación consolidada para desarrollar y mantener Enertika Ops Core. Es la **única fuente de verdad** para:

- Crear nuevos módulos con sistema de permisos
- Implementar controles de UI basados en roles
- Seguir estándares de arquitectura HTMX/SPA
- Garantizar seguridad y consistencia

---
IMPORTANTE:
- No hardcoding
- No emojis in backend
- No code UI in backend
- Logging structured
- Service Layer separated
- Do not modify code until all logic is agreed upon.

## Contenido

### 1. [Arquitectura UI (HTMX + SPA)](01-arquitectura.md)
- Reglas de navegación SPA
- Estructura de archivos y partials
- HTMX patterns y Alpine.js
- **Lectura:** CRITICO

### 2. [Sistema de Permisos](02-permisos.md)
- Jerarquía de roles (sistema y módulo)
- Regla ADMIN crítica
- Validación backend y UI
- **Lectura:** CRITICO

### 3. [Crear Nuevo Módulo](03-crear-modulo.md)
- Checklist paso a paso
- Templates de código
- Registro en sistema
- **Lectura:** CRITICO

### 4. [Service Layer Pattern](04-service-layer.md)
- Separación de responsabilidades
- Catálogos dinámicos
- Timestamps y timezones
- **Lectura:** CRITICO

### 5. [Seguridad y Sesión](05-seguridad.md)
- Tokens Microsoft Graph
- Prevención de ataques (SQL injection, XSS, CSRF)
- Integridad de datos y race conditions
- **Lectura:** CRITICO

### 6. [Estándares UI/UX](06-ui-ux.md)
- Paleta de colores corporativos
- Componentes estándar (botones, badges, KPIs)
- Sistema de animaciones
- **Lectura:** IMPORTANTE

### 7. [WorkflowService](07-workflow.md)
- Sistema centralizado de comentarios
- Notific aciones automáticas
- Integración en nuevos módulos
- **Lectura:** CRITICO

### 8. [Sistema de Correos](08-correos.md)
- Tipos de correos (negocio vs notificaciones)
- Buzones configurables por departamento
- Implementación en módulos
- **Lectura:** CRITICO

### 9. [Integración SharePoint](09-sharepoint.md)
- Upload de archivos a SharePoint
- Metadata y tracking
- Casos de uso comunes
- **Lectura:** IMPORTANTE

### 10. Seguridad Crítica - Configuración de Inicio
- **SECRET_KEY Obligatoria**: La aplicación NO iniciará sin `SECRET_KEY` en el entorno
- **Fail-Fast DB**: Si la conexión a la base de datos falla, el proceso termina inmediatamente (`sys.exit(1)`)
- **Lectura:** CRITICO

### 11. Rendimiento y Debugging
- **N+1 Query Prevention**: Siempre usar batch queries y mapeo en memoria para evitar problemas de rendimiento
  - Ver `modules/admin/service.py:get_users_enriched` como ejemplo de optimización (3 queries vs 101 queries para 100 usuarios)
- **Exception Handling Específico**: NUNCA usar `except Exception` genérico en endpoints
  - Separar `ValueError` (validación - 400), `asyncpg.PostgresError` (BD - 500), otros errores
  - Ver `modules/admin/router.py` para ejemplos correctos
- **Lectura:** CRITICO


---

## Índice Temático (Consulta Rápida)

| ¿Qué necesitas hacer? | Ir a |
|------------------------|------|
| **Crear un nuevo módulo** | [03-crear-modulo.md](03-crear-modulo.md) |
| **Implementar permisos** | [02-permisos.md](02-permisos.md) |
| **Service layer** | [04-service-layer.md](04-service-layer.md) |
| **Tokens Microsoft** | [05-seguridad.md](05-seguridad.md#token-inteligente) |
| **Colores corporativos** | [06-ui-ux.md](06-ui-ux.md#paleta-de-colores) |
| **Comentarios workflow** | [07-workflow.md](07-workflow.md) |
| **Configurar correos** | [08-correos.md](08-correos.md) |
| **Subir a SharePoint** | [09-sharepoint.md](09-sharepoint.md) |
| **Manejar timestamps** | [04-service-layer.md](04-service-layer.md#timestamps) |
| **Validar archivos** | [05-seguridad.md](05-seguridad.md#validacion-archivos) |
| **Catálogos dinámicos** | [04-service-layer.md](04-service-layer.md#catalogos) |
| **HTMX hx-push-url** | [01-arquitectura.md](01-arquitectura.md#navegacion) |
| **Alpine.js vs HTMX** | [01-arquitectura.md](01-arquitectura.md#alpinejs) |
| **Prevenir race conditions** |  [05-seguridad.md](05-seguridad.md#race-conditions) |
| **Componentes UI estándar** | [06-ui-ux.md](06-ui-ux.md#componentes) |
| **Prevenir N+1 queries** | docs/README.md#11-rendimiento-y-debugging |
| **Exception handling correcto** | docs/README.md#11-rendimiento-y-debugging |

---

## Navegación

- [← Volver al proyecto](../../README.md)
- [Ver versión legacy unificada](../GUIA_MAESTRA_LEGACY.md)

---

## Cómo usar esta documentación

**Para desarrolladores nuevos:**
1. Lee [02-permisos.md](02-permisos.md) primero
2. Luego [03-crear-modulo.md](03-crear-modulo.md)
3. Finalmente [04-service-layer.md](04-service-layer.md)

**Para features específicas:**
- Usa el Índice Temático arriba
- Busca con `Ctrl+F` en el archivo relevante

**Para consultas rápidas:**
- Abre solo el archivo que necesitas
- Cada archivo es independiente y completo

---

## Historial de Versiones

- **v2.2** (2026-01-17): Fixes críticos de rendimiento y seguridad
  - Optimización N+1 query en `get_users_enriched` (101 queries → 3 queries)
  - Exception handling específico en router endpoints
- **v2.1** (2026-01-14): Modularización en archivos temáticos. Agregadas secciones de Correos y SharePoint.
- **v2.0** (2025-12-24): Consolidación original de PERMISOS_UI.md, PROJECT_RULES.txt, CREAR_MODULO_CON_PERMISOS.md
