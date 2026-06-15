# Análisis — Deuda técnica: atomicidad de `update_simulacion_padre`

**Fecha:** 2026-06-15
**Origen:** Hallazgo V2 del `/code-review` sobre el fix de recálculo de KPIs por deadline (commit `88979a7`).
**Estado:** Implementado (2026-06-15). Notificaciones quedaron FUERA de la transacción (ver §4),
corrigiendo la recomendación inicial del §4.1 tras verificar que `_send_email` hace HTTP síncrono a Graph.

---

## 1. Problema

`update_simulacion_padre` (`modules/simulacion/service.py:232`) ejecuta **6 writes secuenciales**
sobre una conexión en modo autocommit (`pool.acquire()` sin `conn.transaction()`). Cada `execute`
se comitea por separado, así que una excepción a mitad de camino deja estado parcial sin rollback.

Secuencia de writes (líneas 232–369):

| Paso | Operación | Tabla |
|---|---|---|
| 0.6 | `registrar_cambio_deadline` (hoy inactivo) | `tb_historial_deadline` |
| 3 | `update_oportunidad_padre` | `tb_oportunidades` |
| 3.1 | `recalcular_kpis_sitios_por_deadline` (nuevo, commit `88979a7`) | `tb_sitios_oportunidad` + `tb_simulaciones_adicionales` |
| 3.5 | `insert_historial_estatus` | `tb_historial_estatus` |
| 4 | `_handle_site_updates` → `update_sitios_cascada` | `tb_sitios_oportunidad` |
| 4.5 | `insert_simulaciones_adicionales` | `tb_simulaciones_adicionales` |
| 5 | `_send_update_notifications` | outbox + `pg_notify` |

**Escenario de fallo concreto:** un MANAGER cierra una op multisitio. El paso 3 comitea el nuevo
estatus/deadline del padre → falla la red en el paso 4 (`update_sitios_cascada`). El padre queda
"Entregado" pero los sitios siguen activos y sus KPIs reflejan el deadline viejo. El reporte muestra
entregas tarde fantasma y no hay rollback.

---

## 2. Causa raíz

`get_db_connection` (`core/database.py:54`) entrega una conexión cruda del pool. asyncpg en este modo
es autocommit: no hay unidad transaccional que agrupe los writes.

---

## 3. Solución recomendada

Envolver la **sección completa** (reads de validación + writes) en `async with conn.transaction():`.
No solo los writes, porque:

- `get_oportunidad_for_update` implica un lock `FOR UPDATE` que en autocommit **se libera
  inmediatamente** (es inefectivo hoy). Dentro de una transacción el lock persiste hasta el commit
  → **también cierra el TOCTOU de ediciones concurrentes**.
- Da un snapshot consistente a todas las validaciones (`_validate_status_transition`, conteos de sitios).

```python
async def update_simulacion_padre(self, conn, id_oportunidad, datos, user_context):
    status_map = await self._get_status_ids(conn)        # cache, puede ir fuera
    async with conn.transaction():
        current_data = await self.db.get_oportunidad_for_update(conn, id_oportunidad)  # FOR UPDATE efectivo
        # ...validaciones (0.5, 0.6, 1, 1.5, 2)...
        # ...writes (3, 3.1, 3.5, 4, 4.5)...
    await self._send_update_notifications(...)            # paso 5 — FUERA, ver §4
    return (kpi_sla_val, kpi_compromiso_val, has_negotiated_deadline, es_cierre_terminal)
```

El cambio físico es principalmente indentación. El patrón ya se usa 3 veces en este archivo
(`service.py:751`, `851`, `1317`), por lo que está probado en el setup pgbouncer Transaction Mode (6543).

---

## 4. Puntos finos a respetar

1. **Notificaciones (paso 5) — van FUERA de la transacción, tras el commit.** Dos razones, ambas
   decisivas:
   - `_send_update_notifications` traga `PostgresError` (`logger.error("no critico")`). Si corriera
     dentro de la transacción, ese error la dejaría en estado **abortado** y el `COMMIT` fallaría,
     revirtiendo el write de negocio — exactamente lo contrario de "no crítico".
   - `notify_status_change` → `_send_email` (`core/workflow/notification_service.py:836`) hace un
     **POST síncrono (awaited) a Microsoft Graph API** inline, no solo un insert a outbox. Mantenerlo
     dentro tendría la transacción + el lock `FOR UPDATE` abiertos durante todo el round-trip HTTP,
     bloqueando editores concurrentes y agotando el pool pgbouncer Transaction Mode bajo carga.
   - Post-commit, una falla de notificación queda aislada y el SSE/outbox solo se emite si la
     transacción realmente comiteó (no hay notificación fantasma de un cambio que hizo rollback).
2. **Hora:** `get_current_datetime_mx` usa `datetime.now(tz)` de Python, no `now()` de SQL → no se
   congela dentro de la transacción. Ningún ajuste necesario.
3. **pgbouncer Transaction Mode (6543):** funciona porque la conexión se mantiene durante todo el
   request; no se devuelve a mitad de transacción.

---

## 5. Riesgos / checkpoints antes de mergear

- Confirmar que ningún helper en la cadena (`_handle_site_updates`, `notification_service.notify_*`)
  abra su **propio** `conn.transaction()`. asyncpg lo soporta vía savepoints anidados, pero conviene
  verificar que no dependan de autocommit.
- Verificar que `registrar_cambio_deadline` (paso 0.6, hoy inactivo) tolere correr dentro de la
  transacción cuando se reactive.

---

## 6. Plan de validación

1. Forzar excepción en `insert_historial_estatus` → verificar que `tb_oportunidades` revierte
   (estatus/deadline sin cambios).
2. Test concurrente: dos MANAGERs editan la misma op → el `FOR UPDATE` debe serializar.
3. Cierre normal → confirmar que SSE llega y el outbox encola tras el commit.

---

## 7. Esfuerzo

**Bajo-medio.** Una función, cambio de indentación + verificación de helpers. Sin migración de DB.
