# Levantamientos — Mejoras implementadas 2026-02-27

## Contexto
Sesión de mejoras al módulo de levantamientos. Todos los cambios están en producción.
El registro `LEV_SIN_ASIGNAR` en `tb_config_emails` ya fue insertado manualmente.

## Cambios implementados

### 1. Badge "Nuevo" (visual)
- **Archivo:** `modules/levantamientos/service.py` — query `get_kanban_data`
- **Lógica:** CTE `asignaciones_check` + campo `es_nuevo` calculado en SQL
- **Regla:** `es_nuevo = TRUE` cuando `created_at < 48h` AND sin asignación pivot AND sin `tecnico_asignado_id` legacy
- **Se limpia solo cuando:** se asigna técnico, cambia de estatus, o pasan 48h
- **Visual:** `kanban.html` — borde ámbar + `shadow-[0_0_10px_rgba(245,158,11,0.35)]` + badge "Nuevo" con `animate-ping` en esquina superior derecha de la tarjeta (columna Pendientes)

### 2. Columna Pendientes siempre abierta
- **Archivo:** `templates/levantamientos/partials/kanban.html` línea 53
- `x-data="{ open: false }"` → `x-data="{ open: true }"`

### 3. Botón Reasignar en más columnas
- **Archivo:** `kanban.html`
- Agregado en **En Proceso** (col 3) y **Pospuestos** (col 6)
- Antes solo existía en Pendientes y Agendados
- El modal gestiona permisos internamente (sin guard adicional en template)

### 4. Background task — recordatorio 24h
- **Archivo:** `core/tasks.py` — función `check_levantamientos_sin_asignar_periodically()`
- **Registro:** `main.py` — `asyncio.create_task(...)` en `start_background_tasks()`
- **Intervalo:** cada 6 horas (`interval_seconds=21600`)
- **Primera ejecución:** tras el primer ciclo de espera (no inmediata al startup)
- **Detecta:** `estatus=pendiente` + sin asignar + `created_at > 24h` + `email_enviado=true`
- **Anti-spam:** dict en memoria `{ id_lev: datetime_ultimo_envio }`, salta si < 24h. Limpia entradas > 48h en cada ciclo. Se resetea al reiniciar proceso.
- **Destinatarios:** `EmailRulesService.get_emails_by_event(conn, 'LEVANTAMIENTOS', 'LEV_SIN_ASIGNAR')`
- **Remitente:** `tb_correos_notificaciones WHERE departamento='DEFAULT' AND activo=true`
- **Email:** importancia `high`, template HTML ámbar inline, subject `[Recordatorio] Levantamiento sin asignar: {op_id} — {cliente}`

## Puntos de monitoreo (seguimiento de comportamiento)
1. **Badge "Nuevo"** — verificar que desaparece al asignar técnico o cambiar estatus
2. **Task recordatorio** — revisar logs con prefijo `[LEV_REMINDER]` en Railway
   - `INFO: Recordatorio enviado: lev=... op=...` → éxito
   - `WARNING: No hay destinatarios TO configurados` → falta registro en `tb_config_emails`
   - `ERROR: No hay remitente DEFAULT` → falta config en `tb_correos_notificaciones`
3. **Anti-spam** — al reiniciar el proceso puede enviarse un email extra por levantamiento en el siguiente ciclo (comportamiento esperado)
4. **Botón Reasignar** — disponible en 4 columnas: Pendientes, Agendados, En Proceso, Pospuestos. NO en Completados ni Entregados.

## Configuración BD
```sql
-- Ya insertado (confirmado 2026-02-27):
-- tb_config_emails: modulo='LEVANTAMIENTOS', trigger_value='LEV_SIN_ASIGNAR'
```

## Archivos modificados
| Archivo | Cambio |
|---------|--------|
| `modules/levantamientos/service.py` | CTE asignaciones_check + campo es_nuevo en kanban query |
| `templates/levantamientos/partials/kanban.html` | Badge nuevo, pendientes abierto, botones reasignar |
| `core/tasks.py` | check_levantamientos_sin_asignar_periodically() |
| `main.py` | Registro de nueva tarea en startup |
