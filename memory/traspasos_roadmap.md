# Roadmap: Sistema de Traspasos + Conexion Levantamientos

**Fecha:** 2026-02-08
**Estado:** Fase 1 COMPLETA, Fase 2 COMPLETA (pendiente: SQL en Supabase + notificaciones)

---

## FASE 1: Conectar Levantamientos a Comercial y Simulacion [COMPLETADA]

### Archivos modificados
- [x] `modules/comercial/db_service.py` — LEFT JOINs levantamiento + tecnico
- [x] `modules/simulacion/db_service.py` — idem en query dinamica
- [x] `templates/comercial/partials/cards.html` — render condicional status/tecnico
- [x] `templates/simulacion/partials/cards.html` — idem

---

## FASE 2: Sistema de Traspasos de Proyectos [COMPLETADA]

### Archivos creados/reescritos

**SQL:**
- [x] `scripts/fase3_traspasos.sql` — DDL + seed data (PENDIENTE ejecutar en Supabase)

**Core transfers (nuevo):**
- [x] `core/transfers/__init__.py`
- [x] `core/transfers/schemas.py` — TraspasoEnviar, TraspasoRechazar, etc.
- [x] `core/transfers/db_service.py` — TransferDBService (todas las queries)
- [x] `core/transfers/service.py` — TransferService (logica de negocio, AREA_FLOW)
- [x] `core/transfers/router.py` — endpoints compartidos /transfers/*

**Modulos reescritos:**
- [x] `modules/ingenieria/router.py` + `service.py` (nuevo)
- [x] `modules/construccion/router.py` + `service.py` (nuevo)
- [x] `modules/oym/router.py` + `service.py` (nuevo)
- [x] `modules/proyectos/router.py` + `service.py` (nuevo, reemplaza old API)

**Templates compartidos (nuevos):**
- [x] `templates/shared/partials/card_proyecto.html` — macro render_card
- [x] `templates/shared/partials/lista_proyectos.html` — pendientes + grid
- [x] `templates/shared/partials/modal_enviar_traspaso.html` — checklist docs
- [x] `templates/shared/partials/modal_recibir_traspaso.html` — aceptar
- [x] `templates/shared/partials/modal_rechazar_traspaso.html` — motivos
- [x] `templates/shared/partials/timeline_proyecto.html` — historial

**Templates por modulo (reescritos):**
- [x] `templates/ingenieria/partials/content.html`
- [x] `templates/construccion/partials/content.html`
- [x] `templates/oym/partials/content.html`
- [x] `templates/proyectos/partials/content.html` — vista global + filtros area/status

**Integracion:**
- [x] `main.py` — registrado transfers router

### Pendientes post-implementacion

1. **Ejecutar SQL en Supabase** — `scripts/fase3_traspasos.sql` (DDL + seed data)
2. **Notificaciones** — SSE + Email para eventos de traspaso (estructura lista, falta integrar calls en TransferService)
3. **Limpiar** — `modules/proyectos/schemas.py` tiene schemas viejos (TraspasoProyectoCreate, ProyectoRead) que ya no se usan
4. **Probar** — Verificar flujo completo: Ing → Const → OyM, accept/reject, timeline

### Notas tecnicas

- AREA_FLOW: INGENIERIA→CONSTRUCCION, CONSTRUCCION→OYM (definido en service.py)
- KPIs globales retornan `por_area` dict, no campos planos
- `lista_proyectos.html` usa Jinja2 macro `render_card` de `card_proyecto.html`
- `vista_global=True` flag controla rendering en template (desde router)
- Permisos: viewer para ver, editor para enviar/recibir/rechazar

---

## Bugs Corregidos (2026-03-11)

- **Bug doble-submit:** `enviar_traspaso()` usaba `proyecto.get('ultimo_traspaso_status')` que siempre era None → corregido con `tiene_traspaso_enviado()` en `TransferDBService`
- **`modulo_origen` hardcoded "simulacion":** `_send_notifications()` ahora usa `dest_slug` (enviado) u `origen_slug` (aceptado/rechazado)
- **Notificaciones SSE+email:** implementadas en `core/transfers/service.py` vía `_send_notifications()`
- **Template email traspasos:** `templates/shared/emails/transfers/traspaso_notification.html` ✅ existe
- **Catálogos en BD:** `tb_cat_documentos_traspaso` (14 docs) y `tb_cat_motivos_rechazo` (14 motivos) ✅ poblados
- **Remitentes email:** solo existe `DEFAULT` en `tb_correos_notificaciones` — INGENIERIA/CONSTRUCCION/OYM usan fallback DEFAULT
- **CC traspasos:** `tb_config_emails` sin eventos TRASPASO — CCs vacíos (configurar en Admin si se necesita)
- **Fase 1 fix ✅ (2026-03-18):** `get_traspaso_by_id` ahora incluye JOIN a `tb_oportunidades` → emails aceptado/rechazado tienen `proyecto_nombre` y `cliente_nombre`

---

## Plan de Polish (plan file: inherited-yawning-frog.md)

Plan completo en `.claude/plans/inherited-yawning-frog.md`. Orden recomendado: **Fase 3 → 2 → 4** (Fase 1 ya ✅)

- **Fase 2 (3h):** asignación de responsable por proyecto/área (`tb_proyecto_usuarios`). CRUD en `core/transfers/`, UI en `card_proyecto.html`, modal `modal_asignar_responsable.html`. Notificaciones dirigidas al responsable.
- **Fase 3 (2h):** Comercial ve status de proyectos. JOIN en `core/workflow/service.py get_detalle_oportunidad()`. Sección proyecto en `detalle_oportunidad_modal.html`. Badge en tab Ganadas.
- **Fase 4 (1h):** UI polish — contador docs en modal enviar, tooltip días en área, filtros URL en proyectos.
- **Estado:** PENDIENTE iniciar. Usuario necesita confirmar contexto antes de implementar.

---

## Bug pendiente — Modal enviar traspaso

**Archivo:** `templates/shared/partials/modal_enviar_traspaso.html:46`
**Problema:** Atributo `required` en checkboxes bloquea el submit del navegador
**Fix:** Quitar `required` del HTML — la validación ya existe en `service.py:109-112`
**Estado:** Pendiente de fix
