---
name: UPDATE RETURNING * pierde campos JOIN para notificaciones
description: Los métodos UPDATE RETURNING * no incluyen JOINs — pasar ese dict a _notify_* omite campos como nombre_proveedor
type: feedback
---

Al hacer `UPDATE ... RETURNING *` se obtiene solo el row propio de la tabla, sin JOINs. Si ese dict se pasa directamente a una función de notificación (`_notify_bom`, `_notify_autorizacion`, etc.) que depende de campos calculados por JOIN (ej. `nombre_proveedor`, `aprobador_obra_nombre`), el template de email recibirá esos campos como `None` o ausentes.

**Why:** Se descubrió en BOM Fase D (2026-03-20) que `update_autorizacion_paso_*` devuelve RETURNING * sin JOINs, y `_notify_autorizacion` recibía ese dict — el template usaba `autorizacion.nombre_proveedor` que llegaba vacío.

**How to apply:** Antes de pasar a una función de notificación, mergear el dict enriquecido original (obtenido con SELECT + JOINs) con el dict actualizado:
```python
# aut = get_autorizacion_by_id(...)  ← tiene JOINs (nombre_proveedor, etc.)
# updated = update_autorizacion_paso_obra(...)  ← RETURNING * sin JOINs

await self._notify_autorizacion(conn, {**aut, **updated}, bom, ...)
#                                       ↑ preserva campos JOIN, sobreescribe estatus/fechas actualizados
```
Para INSERT RETURNING * el problema es el mismo — agregar campos manualmente:
```python
aut_enriquecida = {**autorizacion, 'nombre_proveedor': cotizacion.get('nombre_proveedor')}
```
