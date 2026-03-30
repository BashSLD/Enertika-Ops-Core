# Módulo Comercial — Arquitectura y Fixes

## Fixes aplicados (2026-02-24)

### Fix 1 — Tab Historial excluye levantamientos
- **Problema:** tab "Ofertas Generadas" mostraba OPs tipo LEVANTAMIENTO con estatus ENTREGADO
- **Fix en `service.py`:** bloque `if tab == "historial"` añade `AND o.id_tipo_solicitud != {id_levantamiento}` (igual que tab activos)

### Fix 2 — Badge borradores role-based
- **Problema:** `QUERY_GET_BORRADORES_COUNT` sin filtro de usuario → badge mostraba total del módulo
- **Fix:** nueva query `QUERY_GET_BORRADORES_COUNT_BY_USER` en `db_service.py` (agrega `AND creado_por_id = $1`)
- `get_borradores_count(conn, user_context)`: admin ve total, otros solo los propios

## Borradores (arquitectura)
- Tab "Borradores" en `/comercial/ui` — oportunidades con `email_enviado=false` y `fecha_creacion < 24h`
- Auto-limpieza de expirados al cargar el tab (best-effort, `asyncpg.PostgresError`)
- **Endpoints:** `GET /comercial/partials/borradores`, `DELETE /comercial/borrador/{id_oportunidad}`
- **Service:** `get_borradores(conn, user_context)` — admin ve todos; otros solo los propios
- **Queries en `db_service.py`:** `QUERY_GET_BORRADORES`, `QUERY_GET_BORRADORES_BY_USER`, `QUERY_GET_BORRADORES_COUNT`, `QUERY_GET_BORRADORES_COUNT_BY_USER`, `QUERY_GET_EXPIRED_BORRADORES_IDS`
- **Template:** `templates/comercial/partials/borradores.html`
- **Badge:** ámbar, role-based. Solo visible si count > 0
- **JS fix:** `initComercialView` busca tab por `hx-push-url` además de `hx-get`
