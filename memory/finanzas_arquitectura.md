---
name: Finanzas — Arquitectura y patrones
description: Módulo de pagos BOM: flujo, tablas, bugs corregidos y particularidades de implementación
type: project
---

## Propósito
Gestión de pagos BOM ya autorizados. Solo recibe autorizaciones en estatus `AUTORIZADO_FINANZAS`; las lleva a `PAGADO` y crea el comprobante correspondiente en Compras.

## Flujo de pago
```
tb_bom_autorizaciones (AUTORIZADO_FINANZAS)
    ↓  registrar_pago() — transacción atómica
tb_bom_pagos            ← INSERT (1 por autorización, UNIQUE autorizacion_id)
tb_bom_autorizaciones   ← UPDATE estatus = 'PAGADO'
tb_comprobantes_pago    ← INSERT con origen='BOM', id_bom_pago=pago.id
```

## Tablas clave
- `tb_bom_pagos` — moneda es `bpchar` (char), UNIQUE en `autorizacion_id`
- `tb_bom_autorizaciones` — estatus: PENDIENTE → AUTORIZADO_OBRA → AUTORIZADO_DIRECCION → AUTORIZADO_FINANZAS → PAGADO (o RECHAZADO)
- `tb_comprobantes_pago` — origen='BOM'; constraint de duplicados es índice parcial `WHERE id_bom_pago IS NULL` (los de BOM están excluidos)

## Constraint de duplicados (mig 027)
`uq_comprobante_duplicado_no_bom` reemplazó al antiguo `uq_comprobante_duplicado`:
- El índice parcial `WHERE id_bom_pago IS NULL` excluye comprobantes BOM del check de unicidad
- Permite dos pagos BOM al mismo proveedor el mismo día por el mismo monto sin error

## Transacción atómica
`service.py registrar_pago()` usa `async with conn.transaction()` para los 3 writes.
Si cualquiera falla (incluyendo UniqueViolationError de autorizacion_id), todo hace rollback.

## HTMX — swap del modal
`modal_registrar_pago.html` usa `hx-target="#finanzas-main-content"` con `hx-swap="outerHTML"`.
**OJO:** `content.html` tiene `<div id="finanzas-main-content">` como raíz → SIEMPRE `outerHTML`, nunca `innerHTML`.

## Permisos
`puede_registrar_pago` = rol_módulo in ('editor', 'admin') OR rol_sistema == 'ADMIN'
El botón "Registrar Pago" en `lista_pendientes.html` solo aparece si `puede_registrar_pago`.

## KPI query
`get_kpis()` hace LEFT JOIN tb_bom_autorizaciones → tb_bom_pagos.
Tras mig 027, `pendientes_pago` filtra solo por `estatus = 'AUTORIZADO_FINANZAS'` (ya no necesita `bp.id IS NULL`).
`monto_pagado_mes_mxn` suma solo MXN — pagos USD no aparecen en ese KPI (intencional).

## Bugs corregidos (2026-03-25, commit c9fb78f)
1. HTMX swap `innerHTML` → `outerHTML` (IDs duplicados en DOM)
2. Sin transacción → inserts no atómicos (pago huérfano si comprobante falla)
3. Estatus no se actualizaba a PAGADO (faltaba el UPDATE + el valor en CHECK)
4. `uq_comprobante_duplicado` podía fallar para pagos BOM legítimos
5. `BomPagoRead` schema faltaba `registrado_por_nombre`
