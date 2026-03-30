---
name: Proyectos y Comercial — Mejoras 2026-03-18
description: Pre-requisitos para BOM Fases C-E: flags organizacionales usuarios, equipo por proyecto, progress tab en Comercial
type: project
---

## Contexto

Pre-requisitos necesarios antes de implementar BOM Fase C (cotizaciones) y Fase D (autorizaciones).
Diseñados 2026-03-18. Pendientes de implementar.

---

## Pre-A — Flags Organizacionales en tb_usuarios (mig 023)

**Decisión:** agregar campo `rol_organizacional VARCHAR(30) DEFAULT NULL` a `tb_usuarios`.

**Valores posibles:** `NULL` (ninguno), `jefe_ingenieria`, `jefe_construccion`, `director`

**Por qué un campo y no 3 booleans:** un usuario no puede ser simultáneamente jefe de ingeniería
y jefe de construcción — el dropdown comunica exclusividad y es más limpio en Admin UI.

**UI en Admin:**
- Pestaña/formulario de edición de usuario
- Dropdown "Rol Organizacional" al lado del campo `department`
- Opciones: Ninguno / Jefe de Ingeniería / Jefe de Construcción / Director
- Solo ADMIN de sistema puede modificarlo

**Uso en el sistema:**
- `jefe_ingenieria` → aprobador revisión ING en BOM
- `jefe_construccion` → aprobador revisión CONST en BOM
- `director` → aprobador paso 2 en autorizaciones de compra BOM

**Nota:** tb_usuarios ya tiene el patrón de flags booleanos (`es_jefe_levantamientos_default`, etc.).
Para roles organizacionales exclusivos se usa el campo VARCHAR en su lugar.

---

## Pre-B — Equipo por Proyecto (sin migración)

**Tabla existente:** `tb_proyecto_usuarios` (id, id_proyecto, id_usuario, rol_proyecto, area, fecha_asignacion, fecha_fin, activo, asignado_por_id)

**Roles a implementar:**

| rol_proyecto | area | Descripción |
|---|---|---|
| `coordinador_obra` | `CONSTRUCCION` | Coordinador del proyecto. Aprobador paso 1 en autorizaciones BOM |
| `encargado` | `INGENIERIA` | Responsable de ingeniería en este proyecto |
| `encargado` | `CONSTRUCCION` | Responsable de construcción en este proyecto |
| `encargado` | `OYM` | Responsable de OyM en este proyecto |

**UI:** nueva pestaña "Equipo" en detalle del proyecto (`/proyectos/{id}/ui`).

**Permisos para asignar:**
- ADMIN global
- MANAGER global
- Usuario con `rol_organizacional IN ('jefe_ingenieria', 'jefe_construccion')`

**Query para obtener coordinador de obra en autorizaciones BOM:**
```sql
SELECT id_usuario FROM tb_proyecto_usuarios
WHERE id_proyecto = $1 AND rol_proyecto = 'coordinador_obra' AND activo = TRUE
LIMIT 1
```

---

## Pre-C — Progress Tab en Comercial

**Condición:** solo para oportunidades que tienen proyecto activo en `tb_proyectos_gate`.

**Datos a mostrar:**

```
tb_proyectos_gate.area_actual           → área en curso
tb_proyectos_gate.fecha_inicio_area     → días en área (CURRENT_DATE - fecha)
tb_usuarios WHERE rol_organizacional = 'jefe_{area}'  → jefe global del área
tb_proyecto_usuarios WHERE rol='encargado' AND area=area_actual → encargado del proyecto
tb_proyecto_usuarios WHERE rol='coordinador_obra'     → coordinador
```

**Áreas posibles en tb_proyectos_gate.area_actual:**
- `INGENIERIA` → jefe: `jefe_ingenieria`
- `CONSTRUCCION` → jefe: `jefe_construccion`
- `OYM` → responsable: encargado en area OYM

**Ubicación UI:**
- Nueva pestaña "Progreso" en el card/detalle de oportunidad en Comercial
- Se muestra solo si existe `tb_proyectos_gate` vinculado a la oportunidad

---

## BD — Estructura Relevante Verificada (MCP 2026-03-18)

**tb_proyectos_gate:**
- Campos: id_proyecto, id_oportunidad, proyecto_id_estandar, status_fase, area_actual,
  fecha_inicio_area, aprobacion_direccion, fecha_aprobacion, prefijo, consecutivo,
  id_tecnologia, nombre_corto, sharepoint_url, created_at, created_by_id

**tb_proyecto_usuarios:**
- Campos: id, id_proyecto, id_usuario, rol_proyecto, area, fecha_asignacion, fecha_fin, activo, asignado_por_id
- Actualmente vacía (sin datos) — estructura lista para usar

**tb_usuarios (flags existentes):**
- puede_ser_jefe_area, puede_asignarse_simulacion, es_jefe_levantamientos_default, puede_asignarse_levantamientos
- Agregar: rol_organizacional VARCHAR(30) DEFAULT NULL (mig 023)

**tb_proveedores (confirmado para BOM Fases C-E):**
- id_proveedor, rfc, razon_social, nombre_comercial, activo
- Misma tabla que usa módulo Compras ✅
