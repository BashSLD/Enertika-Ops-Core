---
name: Validaciones Pendientes
description: Checklist de features implementadas que requieren prueba funcional en sistema
type: project
---

## Cómo usar
Marcar ✅ cuando se valida en sistema real. Mover a "Validado" una vez confirmado.

---

## Pendientes de Validar

### BOM — Fase D: Autorizaciones (implementada 2026-03-20, mig 025 ✅)
**Flujo feliz:**
- [ ] Seleccionar cotización → tab "Autorizaciones" aparece en BOM `APROBADO_CONST`+
- [ ] Al seleccionar cotización → se crea registro en `tb_bom_autorizaciones` estatus `PENDIENTE`
- [ ] Email enviado al coordinador_obra del BOM con evento `PENDIENTE_OBRA`
- [ ] Coordinador_obra ve botón "Aprobar (Obra)" → click → estatus pasa a `AUTORIZADO_OBRA`
- [ ] Tras aprobar Obra → email al Director (`rol_organizacional = 'director'`) con evento `PENDIENTE_DIRECCION`
- [ ] Director ve botón "Aprobar (Dirección)" → click → estatus pasa a `AUTORIZADO_DIRECCION`
- [ ] Tras aprobar Dirección → email al creador de la autorización (Compras) con evento `PENDIENTE_FINANZAS`
- [ ] ADMIN ve botón "Aprobar (Finanzas)" → click → estatus `AUTORIZADO_FINANZAS`, ítems → `AUTORIZADO`

**Flujo de rechazo:**
- [ ] Botón "Rechazar" en paso Obra → prompt motivo → estatus `RECHAZADO`, paso=OBRA
- [ ] Cotización vuelve a `RECIBIDA`, ítems vuelven a `SIN_COTIZAR`
- [ ] Email de rechazo enviado al creador (Compras)
- [ ] Card de autorización muestra: paso rechazado, nombre del que rechazó, motivo y fecha

**Permisos:**
- [ ] Usuario sin rol coordinador_obra NI ADMIN → no ve botón "Aprobar (Obra)"
- [ ] Usuario sin `rol_organizacional = 'director'` NI ADMIN → no ve botón "Aprobar (Dirección)"
- [ ] No-ADMIN → no ve botón "Aprobar (Finanzas)"
- [ ] Intentar aprobar desde API sin permiso → 400 con mensaje claro

**UI:**
- [ ] Progress tracker (Obra / Dirección / Finanzas) muestra estado correcto en cada paso
- [ ] Nota de aprobación aparece en el card del paso correspondiente
- [ ] Tab vacío (sin cotización seleccionada) → mensaje "Sin autorizaciones"

### BOM — Fase E: Finanzas + Pagos BOM (implementada 2026-03-20, mig 026 pendiente aplicar)
**Setup:** aplicar mig 026 en Supabase. Asignar rol `finanzas editor` a un usuario de prueba.

**Flujo pago:**
- [ ] Autorización en `AUTORIZADO_FINANZAS` → aparece en tab "Pendientes de Pago" del módulo Finanzas
- [ ] Botón "Registrar Pago" visible para finanzas editor+ y ADMIN
- [ ] Modal muestra proyecto, proveedor, monto autorizado correctamente
- [ ] Submit form → pago creado en `tb_bom_pagos` (verificar en Supabase)
- [ ] Comprobante creado en `tb_comprobantes_pago` con `origen='BOM'`, `estatus='PENDIENTE'`, `id_bom_pago` enlazado
- [ ] Registro desaparece de "Pendientes" y aparece en "Historial de Pagos"
- [ ] KPI "Pendientes de Pago" decrementa, "Pagados 30d" incrementa

**Permisos:**
- [ ] Usuario finanzas viewer → NO ve botón "Registrar Pago"
- [ ] Usuario sin acceso a módulo finanzas → 403 al acceder a /finanzas/ui
- [ ] Finanzas editor SÍ puede aprobar paso 3 en tab Autorizaciones del BOM

**UI:**
- [ ] Sidebar muestra "Finanzas" (con ícono 💰) para usuarios con acceso
- [ ] Modal moneda=USD → campo tipo_cambio_usado aparece
- [ ] Doble pago → error "Esta autorización ya tiene un pago registrado"

### BOM — Fase C: Cotizaciones
- [ ] Tab "Cotizaciones" aparece en BOM estatus `APROBADO_CONST` / `EN_REVISION_FINAL` / `APROBADO_FINAL`
- [ ] Tab NO aparece si usuario no tiene `compras editor`
- [ ] Click en tab → carga lazy los ítems disponibles
- [ ] Modal "Nueva Cotización" → autocomplete proveedor funciona (buscar 2+ chars)
- [ ] Seleccionar ítems + capturar precio unitario → subtotal/IVA/total se calculan en tiempo real
- [ ] Guardar cotización → aparece en lista, estatus BORRADOR
- [ ] Botón **Seleccionar** → cambia a SELECCIONADA, ítems pasan a estatus_compra=COTIZADO
- [ ] Botón **Rechazar** → cambia a RECHAZADA, botones desaparecen
- [ ] Cotización SELECCIONADA/RECHAZADA → sin botones de acción

### Comercial — Modal Progreso (Pre-C)
- [ ] Oportunidad CON proyecto (`id_proyecto` no nulo) → botón "Progreso" (violeta) visible en card
- [ ] Oportunidad SIN proyecto → botón no aparece
- [ ] Modal muestra: área actual, días en área (color correcto), jefe área, encargado, coordinador
- [ ] Días >30 → rojo, días >15 → ámbar, días <=15 → normal

### Proyectos — Visita a Obra en card
- [ ] Cada card de proyecto tiene botón "Visita" (teal)
- [ ] Click → abre modal de visita a obra
- [ ] El botón ya NO está en el header global del módulo

### Levantamientos — Visitas de Campo: `/levantamientos/visitas-campo/nueva`
- [ ] El diseño de la página/modal se ve mal — **requiere revisión UI**
- [ ] Funcionalidad: crear visita, agregar viáticos, prorrateo, enviar

### Compras — TC desde XML de Factura
*Feature pendiente de diseñar e implementar.*

**Contexto:** Los XMLs CFDI de facturas en USD incluyen el tipo de cambio en el campo `TipoCambio` del nodo `Comprobante`. Actualmente se extrae la moneda y el total, pero el TC del XML se ignora — se usa el TC del sistema (`tb_tipo_cambio`).

**Lo que falta:**
- [ ] Extraer `TipoCambio` del nodo Comprobante al parsear XML (ya existe `_extract_pago_info` para Tipo P — aplicar patrón similar a facturas normales)
- [ ] Agregar campo `tipo_cambio_xml` a `CfdiData` (schema de parser)
- [ ] Al guardar comprobante: si moneda=USD y `tipo_cambio_xml` presente, ofrecerle al usuario usar ese TC en lugar del del sistema
- [ ] UI en modal de confirm-match: si TC XML difiere del TC sistema, mostrar ambos con opción de seleccionar cuál usar
- [ ] Guardar en `tb_comprobantes_pago` el TC efectivamente usado

**Dependencia:** Ver `memory/compras_cfdi_tipo_p.md` — pendiente más XMLs de EXEL SOLAR para confirmar patrón.

---

### Compras — Carga Masiva de Items desde XML (fuera del flujo normal)
*Feature pendiente de diseñar e implementar.*

**Contexto:** Actualmente los items/materiales se agregan a `tb_materiales_historial` solo como subproducto del flujo de confirmación de match XML→comprobante. Si el usuario tiene XMLs históricos o XMLs de facturas que no pasarán por el flujo de comprobantes, no hay forma de cargarlos al historial.

**Lo que falta:**
- [ ] Diseñar UI: botón "Cargar XMLs al historial" (tab o botón en módulo Materiales / Compras)
- [ ] Endpoint `POST /compras/materiales/cargar-xml` — acepta uno o varios XMLs, extrae conceptos, guarda en `tb_materiales_historial` SIN crear comprobante
- [ ] Deduplicación: si UUID del XML ya existe en historial, omitir (ya hay lógica de prevención por UUID — reutilizar)
- [ ] Auto-categorización por clave SAT (ya existe en flujo normal — reutilizar `get_categorias_by_claves_sat`)
- [ ] Reporte de resultado: N items cargados, M omitidos por duplicado, K sin categoría
- [ ] Decidir: ¿requiere asociar a un proyecto/proveedor o va sin contexto?

---

### Compras — Facturas Parciales
- [ ] Filtro default `SIN_COMPLETAR` muestra PENDIENTE + PARCIALMENTE_FACTURADO
- [ ] Flujo factura parcial: crear, validar estatus PARCIALMENTE_FACTURADO
- [ ] Flujo cierre de remanente: estatus pasa a CERRADO
- [ ] Excel exportado: 2 hojas (Comprobantes + Facturas Vinculadas con RFC/Emisor)
- [ ] Adjuntos en fila: badge PDF (rojo) + XML (naranja, badge si >1, popover nombre_emisor)

---

## Validado ✅

*(Mover items aquí cuando se confirmen en sistema)*
