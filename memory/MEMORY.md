# Enertika Ops Core - Memoria de Proyecto

## Resumen
Plataforma de operaciones empresariales para el sector energético (FastAPI + HTMX + Supabase). Multi-módulo con RBAC, SSE real-time, y auth Microsoft AD.

## Estructura Clave
- `main.py` - Entry point, registro de routers
- `core/` - Infraestructura (DB, auth, permisos, workflow, notificaciones, transfers, materials, bom)
- `modules/` - Módulos de negocio (comercial, simulacion, levantamientos, compras, etc.)
- `templates/` - Jinja2 con HTMX partials
- `docs/` - Guías de desarrollo (9 documentos temáticos)
- `CLAUDE.md` - Reglas del proyecto para Claude

## Patrones Importantes
- **3 capas por módulo:** router.py → service.py → db_service.py
- **HTMX dual render:** detectar AMBOS headers — `hx-request` Y `hx-history-restore-request`. Patrón: `if hx-request AND NOT hx-history-restore-request → partial; else → full page`. Sin esto, Back/Forward rompe el layout (sidebar desaparece).
- **Permisos:** `require_module_access` y `require_manager_access` ya retornan `Depends()` — NO envolver en Depends()
- **DB dual pool:** Transaction Mode (6543) + Session Mode (5432)
- **Timezone:** siempre America/Mexico_City (write aware → asyncpg UTC → read AT TIME ZONE)
- **Error handling HTMX:** NUNCA retornar HTML plano en error — retornar partial completo + toast OOB
- **Toast OOB:** `shared/toast.html` con `hx-swap-oob="afterbegin:#toast-container"`
- **pg_trgm busqueda:** `similarity()` NO sirve para buscar palabras cortas en textos largos — usar `ILIKE + word_similarity()` combo

## Patrones asyncpg
- Ver `memory/feedback_asyncpg_concurrencia.md` — NO usar `asyncio.gather()` con el mismo `conn`

## Regla - Gestión de memoria
Ver `memory/feedback_memoria.md` — dónde guardar info nueva sin saturar MEMORY.md (MEMORY.md = índice, no log; límite 200 líneas)

## Patrones Alpine.js + HTMX
- **NUNCA usar `tojson` dentro de `x-data="..."` con comillas dobles** — rompe el atributo HTML
- **Solución:** pasar JSON via `data-` attribute con comillas simples: `data-foo='{{ lista | tojson }}'`
- **Leer en Alpine:** usar `init() { this.valor = JSON.parse(this.$el.dataset.foo || '[]'); }`
- **Motivo:** HTMX inyecta HTML y Alpine inicializa ANTES de que `<script>` tags internos ejecuten

## Roles
- **Sistema:** ADMIN, MANAGER, USER (NO existe DIRECTOR)
- **Módulo:** viewer, editor, admin (NO existe assignor ni owner)

## BD - Notas de esquema
- Las tres tablas `tb_cat_estatus_global`, `tb_modulos_catalogo`, `tb_departamentos_catalogo` fueron renombradas — existen vistas backward-compat, el código viejo sigue funcionando.
- `tb_cat_estatus_levantamiento` — IDs no predecibles, obtenerlos siempre por `codigo` (pendiente, agendado, en_proceso, pospuesto, completado, entregado)
- **Para verificar estado real de cualquier tabla:** usar MCP Supabase (`list_tables`, `execute_sql`)

## BD - Otras diferencias de nombres vs plan original
- tb_cat_documentos_traspaso: `nombre_documento` (no `nombre`)
- tb_cat_motivos_rechazo: `motivo` (no `nombre`)
- tb_traspasos_proyecto: `status` (no `estatus`), `enviado_por` (no `enviado_por_id`)

## Convención DDL / Migraciones
- Toda modificación de schema va en `migrations/NNN_descripcion.sql` (numeración secuencial)
- Usar `IF NOT EXISTS` / `DO $$ IF NOT EXISTS ... $$` para hacerlos idempotentes
- Ejecutar **ANTES** de desplegar código que dependa del cambio
- **Migraciones 001–025: todas ✅ APLICADAS** (025 validada MCP 2026-03-20 — tb_bom_autorizaciones + índices)
- **Migración 026 ✅ APLICADA** (validada MCP 2026-03-20 — tb_bom_pagos + id_bom_pago/origen en tb_comprobantes_pago)
- **Migración 027 ✅ APLICADA** (2026-03-25 — estatus PAGADO en tb_bom_autorizaciones + índice parcial uq_comprobante_duplicado_no_bom)
- **Migración 028 ✅ APLICADA** (2026-03-26 — tb_visitas_campo.notas TEXT)
- **Próxima migración: 029**
- **IMPORTANTE:** Antes de crear una migración, verificar el número real con `Glob migrations/*.sql`. La memoria puede estar desactualizada.
- **MCP Supabase:** Solo lectura — usar únicamente para verificar estado de BD (SELECT). Para modificar BD, crear archivo en `migrations/` y pedirle al usuario que lo ejecute en Supabase.

## Archivos Grandes (refactorizar cuando se toquen)
Guía general: router.py < 200 líneas, service/db_service < 600 líneas. Sobre 800 es señal de split.
- `modules/simulacion/report_service.py` — ~1,510 líneas → dividir por área de reporte
- `modules/simulacion/router.py` — ~1,086 líneas → separar report_router.py
- `modules/simulacion/db_service.py` — ~1,270 líneas → separar report_db_service.py

## Levantamientos — Reglas de Negocio Clave
- **Ciclos independientes:** cada solicitud tiene su propio ciclo de vida. Cancelar un levantamiento NO cancela la oportunidad comercial asociada.
- **Permisos cancelacion:** ADMIN global, o admin-modulo, o (MANAGER + editor/admin de modulo)
- **motivo_pospone:** campo reutilizado para guardar el motivo de cancelacion
- **Viaticos:** al cancelar se eliminan todos los viaticos activos (`tb_levantamiento_viaticos`)
- Ver detalle visitas de campo + correcciones 2026-03-12: `memory/levantamientos_arquitectura.md`

## Compras — Estado actual (2026-03-18)
Ver detalle completo en `memory/compras_facturas_parciales.md`
- Estatus: `PARCIALMENTE_FACTURADO`, `CERRADO` (mig 021+022 ✅)
- Filtro default: `SIN_COMPLETAR` → `IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')`
- Excel: 2 hojas — Comprobantes + Facturas Vinculadas (con RFC/Emisor completo)
- Adjuntos en fila: PDF (rojo) + XML (naranja, badge si >1, popover nombre_emisor)
- DEV vs PROD SharePoint apuntan al mismo site — cambiar `SHAREPOINT_BASE_FOLDER` en DEV

## BOM — Estado actual (2026-03-18)
Ver roadmap completo Fases A-E en `memory/bom_roadmap_v2.md`
- **Fase A ✅** — flujo 4 aprobadores + email
- **Pre-A ✅** — `rol_organizacional` en tb_usuarios + Admin UI dropdown + badge (mig 023 aplicada)
- **Fase B ✅** — `core/tipo_cambio/` + `tb_tipo_cambio` + tarea periódica + tab Admin (mig 023 aplicada)
- **Pre-B ✅** — Modal "Equipo" en card de proyecto (5 filas: 2 refs org + 3 asignables por dept)
- **Pre-C ✅** — Modal "Progreso" en cards de Comercial (área, días, jefe, encargado, coordinador)
- **Fase C ✅** — Cotizaciones BOM (mig 024 ✅ validada MCP 2026-03-20)
- **Fase D ✅** — Autorizaciones flujo 3 pasos (mig 025 validada MCP 2026-03-20)
- **Fase E ✅** — `modules/finanzas/` + `tb_bom_pagos` (mig 026 ✅); bugs críticos corregidos 2026-03-25 (mig 027 ✅)

## Proyectos — Visita a Obra
- Botón "Visita a Obra" movido del header global → card individual de cada proyecto
- Template: `templates/shared/partials/card_proyecto.html` — botón teal `hx-target="body" hx-swap="beforeend"`
- Pre-relleno del formulario con datos del proyecto: **pendiente (backlog)**
- Endpoint: `GET /proyectos/partials/visita-obra-modal` (sin params por ahora)

## Traspasos — Estado actual
Ver detalle en `memory/traspasos_roadmap.md` y plan `.claude/plans/inherited-yawning-frog.md`
- Bugs principales corregidos 2026-03-11 (doble-submit, modulo_origen, notificaciones SSE+email)
- Fase 1 fix ✅: `get_traspaso_by_id` incluye JOIN → emails con `proyecto_nombre` y `cliente_nombre`
- Plan polish: Fase 3 → Fase 2 → Fase 4 (PENDIENTE iniciar)

## Simulación — Modelo KPI
Ver detalle en `memory/simulacion_kpi_roadmap.md`
- `tb_simulaciones_adicionales` = variantes de UNA MISMA solicitud (cuentan en mes del padre)
- Child opportunities (`parent_id`) = actualizaciones secuenciales — cuentan en su propio mes
- Árbol `parent_id`: profundidad máx 6 niveles — usar CTE recursiva para resolver raíz
- Feature Alta Iteración (implementado 2026-03-13): sección PDF con ciclos de >3 actualizaciones

## Próxima sesión — Agenda
1. **Mobile UI** — bottom sheet ✅, pt-20 fix ✅, modales dvh ✅ — pendiente validación final en dispositivo real
2. **Levantamientos visitas mejoras v1** — ✅ COMPLETADO (commit 86cec3d, 2026-03-25)
3. **Levantamientos visitas v2** — ✅ COMPLETADO (2026-03-26): ingeniero/acompañante, filtro sitios, notas, botón cerrar modales, ciclo de vida lock
4. **Validaciones pendientes** — ver `memory/validaciones_pendientes.md` (BOM Fases C+D+E, Progreso, Visita, Facturas Parciales)
5. **Visita a Obra pre-relleno** — pasar datos del proyecto al formulario del modal (backlog)
6. **Polish traspasos** — plan inherited-yawning-frog.md (Fase 3 → 2 → 4)

## Slash Commands disponibles
- `/simplify` — revisa cambios pendientes de commit, corrige issues de calidad
- `/migrar` — especialista en migración legacy (Excel → BD)
- `/sync-estado [módulo]` — sincroniza MEMORY.md con el estado real del código

## Workflow commits + /simplify
- **Siempre ejecutar `/simplify` antes de commitear** — corre sobre `git diff` (solo cambios sin commit)
- Al pedir commit: correr `git diff` primero para revisar qué se va a incluir, luego proponer mensaje
- Para revisar código ya commiteado: agente Explore sobre archivos específicos, o `git diff HEAD~1`

## Backlog Features (NO implementar aun)
- **Levantamientos mapa sitios:** Google Maps pins
- **Dashboards/Alertas:** Fase 6 pendiente (al final)
- **BOM SSE:** Email es el canal primario. SSE queda en backlog.

## proyecto_id_estandar - Cálculo automático
Formato: `{prefijo}-{consecutivo}-{tecnologia} {nombre_corto}`
Ejemplo: `MX-50055-FV Santa Teresa`
Lógica en: `core/projects/service.py` linea 82-94

## Levantamientos — Visitas de Campo
- Ver arquitectura completa: `memory/levantamientos_arquitectura.md`
- **Migración 028 ✅ APLICADA** — `ALTER TABLE tb_visitas_campo ADD COLUMN notas TEXT`

## Compras — CFDI Tipo P (Complemento de Pago)
Ver detalle completo en `memory/compras_cfdi_tipo_p.md`
- Soporte implementado 2026-03-20: `TipoFactura.PAGO` + `_extract_pago_info()` (moneda real del pago, no MXN del SAT)
- Pendiente (backlog): extracción de `DoctoRelacionado` + campo `tipo_cambio_xml` en CfdiData
- Esperando más XMLs de EXEL SOLAR para confirmar si es caso particular o patrón general

## Mobile Header — Bottom Sheet (2026-03-25) ✅
Patrón implementado en `base.html` + todos los módulos (commits c44682c, 0f5c490):
- Header móvil: botón de **3 puntos** (sin badge) abre un **bottom sheet global**
- El título muestra el nombre del módulo activo via `$store.activeModule?.slug` + `moduleNames` map
- **Slot:** `#mobile-module-actions-slot` en el bottom sheet — cada módulo inyecta sus botones
- **Separador:** `#mobile-actions-separator` — se muestra solo si el slot tiene hijos
- **Patrón por módulo:** `<div id="mobile-actions-template" style="display:none">` + `<script>(function(){...})()</script>`
- El script clona los hijos del template al slot y llama `htmx.process(slot)` para activar atributos hx-*
- El slot se limpia en `htmx:beforeSwap` al navegar entre módulos
- **Notificaciones:** SOLO en el sidebar (badge en nombre de usuario / círculo de iniciales). NO en el botón de 3 puntos.
- Módulos sin acciones (admin, finanzas): no tienen template — el slot queda vacío y el separador oculto
- Módulos con solo buscador (ingenieria, construccion, oym): inyectan el `<input>` directamente al slot
- **`#main-content` usa `pt-20` (80px) en móvil** — `pt-18` no existe en Tailwind default scale y generaba 0px. Header fijo = h-14 (56px), buffer = 24px.

## Modales — Mobile (2026-03-25) ✅
Fixes aplicados en `shared/modals/` + `comercial/modals/` (commit e57e25f):
- **Regla:** usar `max-h-[90dvh]` en lugar de `max-h-[90vh]` — `dvh` = dynamic viewport, excluye chrome del browser (Safari iOS)
- **detalle_oportunidad_modal:** `max-h-[90dvh]` — estructura `flex-col + flex-1 overflow-y-auto` ya estaba bien
- **comentarios_modal:** contenedor ahora `flex flex-col max-h-[90dvh]`, body `flex-1 min-h-0 overflow-y-auto` (antes: `max-h-[70vh]` fijo sin flex)
- **confirmar_seguimiento:** contenedor `max-h-[90dvh] flex flex-col`, body `overflow-y-auto`
- **Patrón correcto para modales altos:** contenedor = `flex flex-col max-h-[90dvh]`, header fijo, body = `flex-1 min-h-0 overflow-y-auto`, footer fijo

## Calculadora de Ventas (Comercial + Simulacion)
Ver detalle en `memory/calculadora_ventas.md`
- Modal compartido: `templates/shared/modals/calculadora_ventas.html`
- Endpoint: `modules/shared/router.py` → `GET /shared/partials/calculadora-ventas?modulo=xxx`
- Icono solo en desktop, con texto en bottom sheet móvil
- **OJO:** factor capacidad panel es `0.71`, NO `0.071`

## Archivos de Referencia
- Finanzas arquitectura + bugs: `memory/finanzas_arquitectura.md`
- Compras facturas parciales: `memory/compras_facturas_parciales.md`
- Compras XML/proveedores/materiales (Fases 1-4 ✅, Fase 5 pendiente): `memory/compras_xml_roadmap.md`
- BOM roadmap + estado: `memory/bom_roadmap_v2.md`
- BOM bugs batch 2026-03-08: `memory/bom_bugs.md`
- Traspasos roadmap + bugs: `memory/traspasos_roadmap.md`
- Simulación KPI + alta iteración: `memory/simulacion_kpi_roadmap.md`
- Simulación modal + adicionales: `memory/simulacion_modal_mejoras.md`
- Levantamientos arquitectura + visitas: `memory/levantamientos_arquitectura.md` ← **Plan v2 visitas EN PROGRESO (2026-03-26)**
- Levantamientos mejoras 2026-02-27: `memory/levantamientos_mejoras_2026-02-27.md`
- Levantamientos UI mobile + iconos: `memory/levantamientos_ui_mobile_icons.md`
- Migración legacy: `memory/migracion_legacy.md`
- asyncpg concurrencia: `memory/feedback_asyncpg_concurrencia.md`
- UPDATE RETURNING * pierde JOINs en notificaciones: `memory/feedback_update_returning_notificaciones.md`
- Gestión de memoria: `memory/feedback_memoria.md`
- PDF service: `memory/pdf_service.md`
- Comercial arquitectura: `memory/comercial_arquitectura.md`
- Proyectos/Comercial mejoras (equipo, progress tab, flags): `memory/proyectos_comercial_mejoras_2026-03-18.md`
- Permisos: `docs/02-permisos.md` + `core/permissions.py`
- Schema BD: `DB_SCHEMA_SNAPSHOT.md`
- Validaciones pendientes: `memory/validaciones_pendientes.md`
