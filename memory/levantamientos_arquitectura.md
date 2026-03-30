# Levantamientos — Arquitectura e Implementación

## Estatus name-based (2026-02-19)
- IDs obtenidos via `LevantamientosDBService.get_estatus_map(conn)` → `{codigo: id}`
- Codigos: `pendiente`, `agendado`, `en_proceso`, `pospuesto`, `completado`, `entregado`
- `update_posponer` y `update_reagendar` reciben `estatus_id` como parámetro
- `get_lista_activos` recibe `ids_activos: List[int]`; `get_lista_terminados` recibe `ids_terminados`
- Analytics queries usan subconsultas en `tb_cat_estatus_levantamiento` (no IDs hardcodeados)
- Template `lista.html` recibe `estatus_filtro` list desde router; badge usa `estatus_color` hex inline

## Visitas de Campo (2026-03-02)
- **Tablas:** `tb_visitas_campo` (entidad) + `tb_visita_campo_levantamientos` (pivot) + `tb_visita_campo_viaticos` + `tb_visita_campo_envios`
- **Migración:** `migrations/004_visitas_campo.sql` — PENDIENTE APLICAR en Supabase
- **DB Service:** `modules/levantamientos/db_service_visitas.py` → `VisitasCampoDBService` + `calcular_prorrateo()`
- **Prorrateo:** división igual, ajuste de centavos al último. Calculado en Python (no SQL).
- **Endpoints modales:** `/modal/visita-campo/nueva`, `/modal/visita-campo/{id}`, `/modal/visita-campo-lev/{id_lev}`
- **Endpoints operaciones:** `POST /visitas-campo`, `POST /visitas-campo/{id}/viaticos`, `DELETE .../{id_viatico}`, `POST /visitas-campo/{id}/enviar`
- **Modal target:** `#modal-content` (igual que el resto de levantamientos)
- **OOB swap:** `tabla_visita_campo_viaticos.html` incluye OOB para `#vc-prorrateo-container`
- **Indicador en modal viaticos:** si lev tiene visitas → banner azul con enlace. `get_visitas_campo_for_lev()` en `LevantamientosDBService`
- **Botón global:** en `kanban.html` header, solo visible si `can_edit`
- **Email:** template `levantamientos/emails/solicitud_viaticos_visita.html`

## Arquitectura multisite y hooks (2026-02-19)
- **Multisite hook (2 momentos):**
  1. Al crear oportunidad (`comercial/service.py:638`): sin sitios → `_crear_sitio_default` + 1 lev
  2. Al confirmar sitios (`confirm_site_upload`, post-transacción): crea levs para sitios 2..N vía `crear_desde_oportunidad` (detecta duplicados automáticamente)
- **QUERY_RELINK_LEVANTAMIENTOS:** en `confirm_site_upload`, revincula todos los levs al primer sitio nuevo antes de borrar sitios viejos
- **tb_sitios_oportunidad:** timestamp se llama `fecha_carga` (NO `created_at`) — bug corregido 2026-02-19 en service.py:70
- **Kanban badges:** `get_kanban_data` calcula `sitio_num` y `sitio_total` en Python (defaultdict) post-query. Template muestra badge índigo "Sitio X/N" en las 6 columnas.
- **Viaticos guard:** `check_viaticos_sent()` se llama ANTES de enviar. Template detecta `ya_enviado` via Jinja2 (ultimo_envio.estatus == 'enviado').
- **Vista Lista:** `GET /levantamientos/partials/lista` → `lista.html`
- **Vista Gráficas:** `GET /levantamientos/partials/graficas` → `graficas.html`, Chart.js CDN, 4 charts.
- **Nuevos endpoints en:** `router_levantamientos_nuevos.py` (dentro de `register_nuevos_endpoints`)
- **Nuevas queries en:** `modules/levantamientos/db_service.py` (get_lista_activos, get_lista_terminados, get_usuarios_tecnicos, get_distribucion_estatus, get_carga_tecnicos, get_tendencia_semanal, get_tiempos_y_costos)

## Responsable vs Acompañante + Adjuntos + Auto-asignar (2026-02-25)

### DDL (en migrations/002_levantamientos_responsable.sql — ya ejecutado)
```sql
ALTER TABLE tb_levantamiento_asignaciones
ADD COLUMN IF NOT EXISTS es_responsable BOOLEAN NOT NULL DEFAULT FALSE;
-- UNIQUE constraint uq_lev_asig_lev_tecnico en (id_levantamiento, tecnico_id)
```

### Cambios implementados
- **db_service.py:** `get_tecnicos_asignados_detalle` incluye `es_responsable`; nuevas queries `get_responsable_asignado`, `update_responsable` (ON CONFLICT); `get_usuarios_viaticos(conn, id_lev=None)` filtra a asignados con fallback
- **schemas.py:** `AssignmentForm` tiene `responsable_id: Optional[UUID]`
- **service.py:** `assign_responsables(... responsable_id=None)` — guarda `es_responsable=True` en INSERT; auto-responsable si solo 1 técnico
- **router.py:** `get_assign_modal` pasa `current_responsable_id` (str); `assign_responsables_endpoint` pasa `form.responsable_id`
- **assign_modal.html:** Radio (Responsable) + Checkboxes (Acompañantes) con Alpine.js; hidden inputs para submission real vía `<template x-for>`
- **router_modales.py:** `get_modal_viaticos` usa `get_usuarios_viaticos(conn, id_lev)`; `get_modal_entrega` pasa `adjuntos_previos`; `get_modal_reagendar` pasa `responsable_actual` e `is_jefe`
- **entrega_modal.html:** sección de adjuntos previos en modo lectura (dark theme)
- **reagendar_modal.html:** bloque confirmación ámbar si hay responsable previo; checkbox `asumir_responsable`
- **router_operaciones.py:** `reagendar_endpoint` recibe `asumir_responsable: bool = Form(False)`; auto-asigna como responsable (Caso A/B)
- **detalle_levantamiento_modal.html:** badge "Responsable" azul en técnicos con `tech.es_responsable`

### Alpine.js pattern en assign_modal
```html
x-data="{ responsableId: '', tecnicoIds: [] }"
x-init="responsableId = $el.dataset.currentResponsable || ''; try { tecnicoIds = JSON.parse($el.dataset.currentTecnicos || '[]').map(function(id){ return String(id); }); } catch(e) { tecnicoIds = []; }"
data-current-responsable="{{ current_responsable_id or '' }}"
data-current-tecnicos='{{ current_tecnico_ids | tojson }}'
```
Radios usan `name="_resp_radio"` (visual only); hidden inputs `<template x-for>` manejan submission real.

## Mejoras 2026-02-25

### Flag puede_asignarse_levantamientos
- **DDL ejecutado:** `ALTER TABLE tb_usuarios ADD COLUMN puede_asignarse_levantamientos BOOLEAN NOT NULL DEFAULT FALSE`
- **Criterio:** `puede_asignarse_levantamientos = true OR permiso módulo levantamientos` (OR, no reemplaza)
- **Afecta:** `service.py:get_usuarios_para_asignacion` (modal) y `db_service.py:get_usuarios_tecnicos` (filtro lista)
- **Admin UI:** toggle ámbar — endpoint `POST /admin/users/{id}/levantamiento-flag`
- **Patrón idéntico a:** `puede_asignarse_simulacion` en simulación

### Viáticos — TO editable
- **Modal:** campo TO pre-poblado con `to_configurados` (desde `tb_config_emails`), editable con tag-chips
- **Validación frontend:** `submitGuard()` impide envío si `tagsTo` está vacío
- **Fallback backend:** si `to_destinatarios` llega vacío, usa `to_configurado` de BD (`router_operaciones.py`)
- **`tb_config_emails` queries:** buscan `modulo IN ('LEVANTAMIENTOS', 'GLOBAL')` — reglas GLOBAL aplican a viáticos
- **Evento admin:** `SOLICITUD_VIATICOS` en fallback de `admin/service.py`

## Fecha Ideal del Solicitante (2026-03-04)
- **Columna:** `tb_levantamientos.fecha_ideal_solicitante TIMESTAMPTZ` (mig 006, ✅ aplicada)
- **Captura:** Paso 3 formulario comercial — fecha existente + hora opcional (solo LEVANTAMIENTO); `router.py POST /notificar` detecta `codigo_interno='LEVANTAMIENTO'`, combina fecha+hora, escribe en `tb_levantamientos`
- **Footer correo:** fila "Fecha Requerida" visible para TODOS los seguimientos (`is_followup=true`). LEVANTAMIENTO: placeholder `__FECHA_IDEAL__` reemplazado por JS pre-submit. Otros: valor servidor `op.fecha_ideal_usuario`
- **`notification_service.py`:** query agrega `tipo_sol.codigo_interno as tipo_solicitud_codigo` → `op.tipo_solicitud_codigo` en template
- **`db_service.py`:** `get_levantamiento_base()` incluye `solicitado_por_id` + `fecha_ideal_solicitante`; nuevo método `update_fecha_ideal_solicitante()`
- **`service.py`:** `get_kanban_data()` incluye `solicitado_por_id` + `fecha_ideal_solicitante`
- **Kanban:** chip purple con reloj en las 6 columnas; botón editar para solicitante propio o can_edit
- **Modal:** `GET /modal/fecha-ideal/{id}` → `fecha_ideal_modal.html`; `POST /operaciones/fecha-ideal/{id}` → valida permisos → recarga kanban

## Mejoras 2026-02-27
Detalle completo en `memory/levantamientos_mejoras_2026-02-27.md`
- Badge "Nuevo" ámbar con animate-ping (es_nuevo calculado en SQL, sin DDL)
- Columna Pendientes siempre abierta
- Botón Reasignar en En Proceso y Pospuestos
- Background task `check_levantamientos_sin_asignar_periodically()` cada 6h (core/tasks.py + main.py)
- `tb_config_emails` con `LEV_SIN_ASIGNAR` ya insertado en BD

## Visitas de Campo v2 — ✅ IMPLEMENTADO (2026-03-26)

Commits: `653f134` (v2 base), `d2cad6c` (botón cerrar), `830eb2f` (ciclo de vida)

### Resumen de cambios
- **A1:** Fix 500 assign modal — UUID→str en `get_asignaciones_actuales()`
- **A2:** levStatusModal removido; Iniciar/Completar pasan a `hx-post` directo
- **A3:** `get_levantamientos_disponibles()` filtra `pendiente/agendado/pospuesto` + excluye sitios ya en otra visita
- **B1-B2:** Crear visita con `ingeniero_id`, `acompaniante_id`, `notas`; selects en el formulario
- **B3:** POST acepta nuevos campos; confirmación ámbar si hay responsable previo (`force_replace`)
- **B4:** `propagar_acompaniante_visita()` + `check_levantamientos_con_responsable()` + `update_notas_visita()` en `db_service_visitas.py`
- **B5:** Sección notas editable en detalle + `PATCH /visitas-campo/{id}/notas`
- **Mig 028 ✅:** `tb_visitas_campo.notas TEXT`

### Ciclo de vida (sin DDL — computado)
- `todos_completados` = subconsulta en `get_visita()` / `get_all_visitas()`: tiene levs Y ninguno fuera de `completado`/`entregado`
- **Badge en lista:** Pendiente (amber) → Activa (emerald) → Cerrada (slate)
- **Lock en detalle:** `can_edit and not visita_cerrada` — bloquea eliminar, toggle viáticos, agregar viático, notas
- **Envío de correo siempre activo** aunque esté cerrada (por si se omitió)
- Banner informativo gris cuando `visita_cerrada=true`

### Decisiones de diseño
- `es_responsable=True` → ingeniero principal; `es_responsable=False` → acompañante
- Notas: campo TEXT libre en `tb_visitas_campo`, NO tabla separada, NO historial — cada guardado reemplaza el anterior
- **Lock de notas (Alpine):** si hay notas → solo lectura por defecto; botón "Editar notas" visible solo para `can_edit and not visita_cerrada`; al guardar/cancelar vuelve a solo lectura automáticamente (`@htmx:after-request="desbloqueado = false"`)

## Visitas de Campo — Correcciones 2026-03-12

- **Fix 1 (atomicidad):** `crear_visita_campo()` envuelto en `async with conn.transaction()` — create_visita + sync_agendado + viaticos en una sola transacción
- **Fix 2 (email):** `{{ v.usuario_nombre or "Sin asignar" }}` en template email
- **Fix 3 (validación fechas):** fechas individuales validadas contra período de la visita antes de la transacción
- **Fix 4 (Alpine.js):** `preseleccionado` movido a `data-preseleccionado='{{ ... | tojson }}'` — leído con `JSON.parse(this.$el.dataset.preseleccionado)`
- **Fix 5 (LIMIT):** `get_envios_visita()` retorna máximo 20
- **Fix 6 (fallback usuarios):** `get_usuarios_para_visita()` hace fallback a todos los activos si no hay asignaciones
- **Fix 7 (prorrateo):** `metodo_prorrateo` pasado como variable al email template
- **Fix 8 (viáticos opcionales):** columna `viaticos_opcionales` + toggle UI + PATCH endpoint + email condicional
