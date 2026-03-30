---
name: BOM Roadmap v2 — Fases A-E
description: Estado completo BOM, arquitectura Fases B-E (cotizaciones, autorizaciones, Finanzas, tipo de cambio)
type: project
---

## Estado Actual BOM (2026-03-20)

**Fase A ✅** flujo 4 aprobadores (ING → OBRA → CONST → FINAL) + email. Mig 020.
**Fase B ✅** `core/tipo_cambio/` + `tb_tipo_cambio` + tarea periódica. Mig 023.
**Fase C ✅** Cotizaciones BOM (`tb_bom_cotizaciones` + `tb_bom_cotizacion_items`). Mig 024.
**Fase D ✅** Autorizaciones 3 pasos (Obra → Dirección → Finanzas). Mig 025 validada MCP 2026-03-20.
- `_notify_autorizacion()` en `core/bom/service.py` + template `bom_autorizacion.html`
- Tab "Autorizaciones" en BOM content desde `APROBADO_CONST`
- Finanzas paso 3: solo ADMIN hasta Fase E (se actualizará cuando exista módulo finanzas)

**Fase E ✅** — Módulo Finanzas (`modules/finanzas/`) + `tb_bom_pagos`. Mig 026 pendiente aplicar.
- `modules/finanzas/` con router/service/db_service/schemas (3 capas)
- `/finanzas/ui` dashboard: KPIs + tab Pendientes + tab Historial
- Paso 3 de autorizaciones ahora acepta finanzas editor+ (no solo ADMIN)
- Pago crea entrada en `tb_comprobantes_pago` con `origen='BOM'` para trazabilidad en Compras

---

## Orden de Implementación

```
Pre-A:  flags tb_usuarios (es_jefe_ingenieria, es_jefe_construccion, es_director) → Admin UI
Pre-B:  Proyectos → pestaña "Equipo" → coordinador_obra + encargados por área
Pre-C:  Comercial → pestaña "Progreso" → card área actual, días, jefes, encargados
Fase B: core/tipo_cambio/ + tb_tipo_cambio (mig 023)
Fase C: Cotizaciones BOM (mig 024)
Fase D: Autorizaciones (mig 025)
Fase E: Módulo Finanzas + comprobantes + reporte costos en card proyecto (mig 026)
```

---

## Pre-A — Flags Organizacionales en tb_usuarios (mig 023)

**Decisión UI:** dropdown `rol_organizacional` al lado del campo `department` en Admin.
- Valor único por usuario: `Ninguno / Jefe de Ingeniería / Jefe de Construcción / Director`
- Almacenado como campo `rol_organizacional VARCHAR(30) DEFAULT NULL` en tb_usuarios
- **Motivo:** más limpio que 3 booleans separados; comunica exclusividad; escala si se añaden roles

**Why:** los flags globales existen (es_jefe_levantamientos_default) pero el dropdown evita que alguien
sea "Jefe de Ing" y "Jefe de Const" simultáneamente — lo cual no tiene sentido organizacionalmente.

**Permisos para asignar:** solo ADMIN de sistema puede cambiar rol_organizacional desde Admin UI.

**Uso en BOM:**
- `es_jefe_ingenieria` (rol_organizacional = 'jefe_ingenieria') → aprobador paso ING
- `es_jefe_construccion` → aprobador paso CONST
- `es_director` → aprobador paso FINAL (Dirección en autorizaciones de compra)

---

## Pre-B — Coordinador de Obra y Equipo por Proyecto

**Tabla:** `tb_proyecto_usuarios` (ya existe, sin migración necesaria)
- Estructura: `id_proyecto, id_usuario, rol_proyecto, area, activo`

**Roles a usar:**

| rol_proyecto | area | Descripción |
|---|---|---|
| `coordinador_obra` | `CONSTRUCCION` | Coordinador del proyecto — aprobador paso 1 autorización BOM |
| `encargado` | `INGENIERIA` | Responsable de ing en este proyecto |
| `encargado` | `CONSTRUCCION` | Responsable de const en este proyecto |
| `encargado` | `OYM` | Responsable de OyM en este proyecto |

**Permisos para asignar:** ADMIN global, MANAGER global, o usuario con `rol_organizacional` de jefe
(es_jefe_ingenieria, es_jefe_construccion).

**UI:** nueva pestaña "Equipo" en detalle del proyecto.

---

## Pre-C — Progress Tab en Comercial

**Condición:** solo para oportunidades que tienen proyecto activo en `tb_proyectos_gate`.

**Datos mostrados:**
```
Área actual: INGENIERIA  •  18 días en esta área
Jefe del área: [usuario con rol_organizacional = 'jefe_ingenieria']
Encargado del proyecto: [tb_proyecto_usuarios WHERE rol='encargado' AND area=area_actual]
Coordinador de obra: [tb_proyecto_usuarios WHERE rol='coordinador_obra']
OyM (si aplica): [tb_proyecto_usuarios WHERE rol='encargado' AND area='OYM']
```

---

## Fase B — Tipo de Cambio Banxico (mig 023)

**Módulo:** `core/tipo_cambio/` — service + router + db_service

**Tabla:**
```sql
tb_tipo_cambio(
  id SERIAL PK,
  fecha DATE UNIQUE NOT NULL,
  tasa_mxn NUMERIC(10,4) NOT NULL,
  fuente VARCHAR(20) DEFAULT 'BANXICO',
  creado_en TIMESTAMPTZ DEFAULT NOW()
)
```

**Config requerida:** variable de entorno `BANXICO_TOKEN`
**Serie Banxico:** SF43718 (tipo de cambio FIX interbancario USD/MXN)
**Refresco:** consulta al startup + endpoint manual de admin para forzar actualización
**Uso en BOM:** mostrar total estimado en MXN y USD con nota "Tasa del {fecha}"

---

## Fase C — Cotizaciones BOM (mig 024)

**Flujo:**
1. BOM llega a `APROBADO_CONST`
2. Compras puede ver el BOM y sus items
3. Compras selecciona 1+ items del mismo proveedor → crea Solicitud de Cotización (SC)
4. Compras adjunta PDF de cotización recibida del proveedor → PDF a SharePoint
5. Compras marca cotización ganadora → genera autorización automáticamente

**Tabla `tb_bom_cotizaciones`:**
```
id UUID PK,
bom_id UUID FK tb_bom,
proveedor_id UUID FK tb_proveedores,
nombre_proveedor TEXT (snapshot),
moneda CHAR(3) DEFAULT 'MXN',
subtotal NUMERIC(14,2),
iva NUMERIC(14,2),
total NUMERIC(14,2),
estatus VARCHAR(20): BORRADOR | RECIBIDA | SELECCIONADA | RECHAZADA,
pdf_url TEXT (SharePoint),
notas TEXT,
creado_por UUID FK tb_usuarios,
creado_en TIMESTAMPTZ,
actualizado_en TIMESTAMPTZ
```

**Tabla `tb_bom_cotizacion_items`:**
```
id UUID PK,
cotizacion_id UUID FK,
bom_item_id UUID FK tb_bom_items,
precio_unitario NUMERIC(12,4),
cantidad NUMERIC(10,2),
moneda CHAR(3),
subtotal_linea NUMERIC(14,2)
```

**Cambios en `tb_bom_items`:**
```
+ moneda CHAR(3) DEFAULT 'MXN'
+ precio_unitario NUMERIC(12,4)        -- referencia presupuestal
+ estatus_compra VARCHAR(20): SIN_COTIZAR | COTIZADO | AUTORIZADO | PAGADO
```

**Nota:** `tb_proveedores` es la misma tabla que usa Compras (`id_proveedor`, `rfc`, `razon_social`, `nombre_comercial`).

---

## Fase D — Autorizaciones de Compra (mig 025)

**Flujo:**
```
Cotización SELECCIONADA
  → tb_bom_autorizaciones creada (PENDIENTE)
  → email al coordinador_obra del proyecto
  → Coordinador aprueba → AUTORIZADO_OBRA
  → email al Director (rol_organizacional = 'director')
  → Director aprueba → AUTORIZADO_DIRECCION
  → email a admin módulo Finanzas
  → Finanzas aprueba → AUTORIZADO_FINANZAS
  → Compras puede realizar el pedido
Cualquier paso puede → RECHAZADO → vuelve a Compras (cotización a RECIBIDA)
```

**Tabla `tb_bom_autorizaciones`:**
```
id UUID PK,
cotizacion_id UUID FK UNIQUE,
bom_id UUID FK (denorm),
proyecto_id UUID FK (denorm),
monto_total NUMERIC(14,2),
moneda CHAR(3),
tipo_cambio_snapshot NUMERIC(10,4),

estatus VARCHAR(30): PENDIENTE | AUTORIZADO_OBRA | AUTORIZADO_DIRECCION
                   | AUTORIZADO_FINANZAS | RECHAZADO,

-- Paso 1: Coordinador Obra del proyecto
aprobador_obra_id UUID FK,
fecha_aprobacion_obra TIMESTAMPTZ,
nota_obra TEXT,

-- Paso 2: Director (rol_organizacional = 'director')
aprobador_direccion_id UUID FK,
fecha_aprobacion_direccion TIMESTAMPTZ,
nota_direccion TEXT,

-- Paso 3: Admin Finanzas (permiso módulo finanzas admin/manager)
aprobador_finanzas_id UUID FK,
fecha_aprobacion_finanzas TIMESTAMPTZ,
nota_finanzas TEXT,

-- Rechazo
rechazado_en_paso VARCHAR(20),
rechazado_por UUID FK,
motivo_rechazo TEXT,
fecha_rechazo TIMESTAMPTZ,

creado_por UUID FK,
creado_en TIMESTAMPTZ
```

---

## Fase E — Módulo Finanzas + Comprobantes (mig 026)

**Módulo:** `modules/finanzas/` — acceso configurado desde Admin igual que cualquier módulo.
**Roles:** viewer / editor / admin (sin cambios al sistema RBAC).

**Flujo pago:**
1. Finanzas ve autorizaciones en `AUTORIZADO_FINANZAS` pendientes de pago
2. Finanzas registra pago → crea `tb_bom_pagos` + sube comprobante PDF a SharePoint
3. Sistema crea automáticamente registro en `tb_comprobantes_pago` con `estatus = PENDIENTE_XML`
4. En módulo Compras aparece el comprobante listo para que Compras suba el XML correspondiente
5. Compras sube XML → `estatus = XML_CARGADO` → `COMPLETADO`

**Tabla `tb_bom_pagos`:**
```
id UUID PK,
autorizacion_id UUID FK,
monto_pagado NUMERIC(14,2),
moneda CHAR(3),
tipo_cambio_usado NUMERIC(10,4),
fecha_pago DATE,
referencia_bancaria VARCHAR(100),
comprobante_url TEXT (SharePoint PDF),
registrado_por UUID FK,
registrado_en TIMESTAMPTZ
```

**Tabla `tb_comprobantes_pago`** (compartida Finanzas ↔ Compras):
```
id UUID PK,
pago_id UUID FK tb_bom_pagos,
proyecto_id UUID FK (denorm),
proveedor_id UUID FK,
nombre_proveedor TEXT (snapshot),
monto NUMERIC(14,2),
moneda CHAR(3),
pdf_url TEXT,
xml_url TEXT NULL,
rfc_emisor VARCHAR(20) NULL,
nombre_emisor TEXT NULL,
estatus VARCHAR(20): PENDIENTE_XML | XML_CARGADO | COMPLETADO,
origen VARCHAR(20) DEFAULT 'FINANZAS',
creado_en TIMESTAMPTZ,
actualizado_en TIMESTAMPTZ
```

**Reporte de Costos (en card del proyecto — MVP):**

| Concepto | Fuente |
|---|---|
| Presupuestado BOM | SUM(precio_unitario × cantidad) en tb_bom_items |
| Comprometido | SUM(total) cotizaciones SELECCIONADAS |
| Autorizado | SUM(monto_total) autorizaciones AUTORIZADO_FINANZAS |
| Pagado | SUM(monto_pagado) en tb_bom_pagos |
| Variación | Pagado − Presupuestado |

Filtros reporte completo (pendiente Fase E+): proyecto, proveedor, fechas, moneda.

---

## Migraciones Requeridas

| # | Contenido | Estado |
|---|---|---|
| 023 | `tb_tipo_cambio` + `rol_organizacional` en `tb_usuarios` | ✅ APLICADA (validada MCP 2026-03-20) |
| 024 | `tb_bom_cotizaciones` + `tb_bom_cotizacion_items` + campos en `tb_bom_items` | ✅ APLICADA (validada MCP 2026-03-20) |
| 025 | `tb_bom_autorizaciones` | ✅ APLICADA (validada MCP 2026-03-20) |
| 026 | `tb_bom_pagos` + cols `id_bom_pago`/`origen` en `tb_comprobantes_pago` | ✅ APLICADA (validada MCP 2026-03-20) |

**IMPORTANTE:** verificar número real con `Glob migrations/*.sql` antes de crear — la memoria puede desfasarse.

---

## Decisiones Pendientes (Items de Roadmap v2 original)

| # | Pregunta | Estado |
|---|---|---|
| 1 | Edición en EN_REVISION_ING/CONST — ¿libre o antes de aprobar? | Pendiente |
| 2 | Modal items: tabs, colapsable, o 3 modales? | Pendiente |
| 3 | Bulk edit — campos MVP? | Pendiente |
| 4 | Aprobador final BOM: config global u Opción B flag? | Pendiente (ligado a rol_organizacional Pre-A) |
| 5 | Suplencias: por BOM, global, o tabla delegaciones? | Pendiente |
