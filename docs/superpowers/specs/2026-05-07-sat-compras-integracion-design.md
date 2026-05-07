# SAT + Compras: Integración y mejoras de UI

**Fecha:** 2026-05-07  
**Módulo:** Compras / SAT Inbox  
**Estado:** Aprobado

---

## Contexto

El flujo actual obliga al usuario a navegar entre dos vistas separadas (`/compras/ui` y `/compras/sat/ui`) para revisar comprobantes pendientes y vincularlos con CFDIs descargados del SAT. Esto genera fricción, especialmente cuando los candidatos no hacen match automático y hay que buscarlos manualmente.

Problemas adicionales reportados:
- El header de `/compras/sat/ui` ocupa espacio innecesario
- No hay columna de tipo CFDI en la tabla de inbox
- El botón "Exportar Excel" está enterrado en el header de escritorio
- El auto-match no produce logs visibles cuando falla

---

## Cambios

### 1. UI rápidos en `/compras/sat/ui`

- **Eliminar** el card de encabezado (badge "Compras SAT" + título "Inbox SAT — ISA" + descripción). El formulario de descarga queda como primer elemento visible.
- **Agregar columna Tipo** en `sat_inbox_table.html` entre RFC y Total. Muestra badge de color con el `tipo_detectado`:
  - NORMAL → verde "Factura"
  - ANTICIPO → naranja "Anticipo"
  - CIERRE_ANTICIPO → azul "Cierre Anticipo"
  - PAGO → cyan "Comp. Pago"
  - NOTA_CREDITO → púrpura "Nota Crédito"

### 2. Exportar Excel — mover a zona de filtros

- **Eliminar** el botón `<a id="export-excel-btn">` del header desktop en `content.html`.
- **Agregar** ícono de descarga (`↓`) junto al botón "Filtros" en `tabla_comprobantes.html`. Mismo estilo que el botón de filtros (borde gris, hover suave). El `href` es idéntico al que tenía en el header, incluyendo los parámetros de fecha del form activo.
- El botón mobile en `#mobile-actions-template` no cambia.

### 3. Badge SAT en filas de comprobantes + modal de candidatos

#### 3a. Subquery de conteo en `listar_comprobantes`

En `db_service.py`, la query principal de comprobantes agrega un campo `sat_candidatos_count` vía subquery correlacionado:

```sql
(
  SELECT COUNT(*)
  FROM tb_sat_inbox i
  WHERE i.estado = 'pendiente'
    AND ABS(i.total - c.monto) <= 1.00
    AND (
      i.nombre_emisor ILIKE '%' || c.beneficiario_orig || '%'
      OR c.beneficiario_orig ILIKE '%' || i.nombre_emisor || '%'
      OR EXISTS (
        SELECT 1 FROM tb_proveedores p2
        WHERE p2.id_proveedor = c.id_proveedor
          AND p2.rfc = i.rfc_emisor
      )
    )
) AS sat_candidatos_count
```

Solo se aplica cuando `c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO')`.

#### 3b. Badge en `row_comprobante.html`

Si `sat_candidatos_count > 0`, mostrar badge pequeño (naranja o teal) con texto "SAT · N" en la columna de acciones/estatus. El badge tiene:

```html
hx-get="/compras/sat/comprobante/{id_comprobante}/candidatos"
hx-target="#sat-candidatos-modal-container"
hx-swap="innerHTML"
```

El `#sat-candidatos-modal-container` es un div vacío al final de `content.html` (al lado del modal upload existente).

#### 3c. Nuevo endpoint `GET /compras/sat/comprobante/{id_comprobante}/candidatos`

En `sat_router.py`:
- Obtiene el comprobante (monto, beneficiario, proveedor RFC)
- Busca SAT inbox items con criterio relajado: `ABS(total - monto) <= 1.00` AND (nombre ILIKE OR RFC match)
- Devuelve `sat_candidatos_modal.html` con la lista (puede ser vacía)

#### 3d. Nuevo template `sat_candidatos_modal.html`

Secciones:
1. **Header**: nombre del comprobante, monto, fecha
2. **Lista de candidatos** (radio buttons): RFC emisor, nombre emisor, monto, fecha CFDI, badge de tipo
3. **Búsqueda manual** (siempre visible si lista vacía; colapsable con "¿No encuentras el CFDI?" si hay candidatos):
   - Input de texto con `hx-get="/compras/sat/comprobante/{id}/candidatos?q=texto"` y `hx-trigger="input delay:400ms"`
   - Actualiza solo la lista de candidatos dentro del modal
4. **Footer**: botón Cancelar + botón "Confirmar vinculación" (disabled si nada seleccionado)

#### 3e. Nuevo endpoint `POST /compras/sat/inbox/{inbox_id}/match-desde-comprobante`

En `sat_router.py`:
- Recibe `inbox_id` (path) + `comprobante_id` (form)
- Reutiliza `_procesar_match_unico(conn, inbox_id, comprobante_id, user_id)`
- Respuesta:
  - Toast OOB (éxito o error)
  - Fila del comprobante actualizada OOB via `hx-swap-oob="outerHTML"` en `#comprobante-row-{id_comprobante}` — el badge SAT desaparece (sat_candidatos_count se recalcula)
  - Cierra el modal vaciando `#sat-candidatos-modal-container`

Para que el OOB de la fila funcione, `row_comprobante.html` debe tener `id="comprobante-row-{{ comprobante.id_comprobante }}"` en el `<tr>`.

### 4. Logging en Auto-Match

En `confirm_auto_match` (`sat_router.py`):

```python
logger.info("Auto-match iniciado: %d pares recibidos", len(matches))
# dentro del loop, por cada par:
logger.info("Procesando match inbox=%s comprobante=%s", inbox_id_str, comprobante_id_str)
# al final:
logger.info("Auto-match completado: %d exitosos, %d errores", procesados, errores)
```

Esto permite diagnosticar si el form envía los valores correctos y qué pasa con cada par.

---

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `templates/compras/partials/sat_inbox_content.html` | Eliminar card header |
| `templates/compras/partials/sat_inbox_table.html` | Agregar columna Tipo |
| `templates/compras/partials/content.html` | Eliminar botón Excel del header |
| `templates/compras/partials/tabla_comprobantes.html` | Agregar ícono Excel junto a Filtros |
| `templates/compras/partials/row_comprobante.html` | Agregar id al tr + badge SAT |
| `templates/compras/partials/sat_candidatos_modal.html` | Nuevo template |
| `modules/compras/db_service.py` | Subquery sat_candidatos_count |
| `modules/compras/sat_db_service.py` | Nueva función buscar_candidatos_para_comprobante |
| `modules/compras/sat_router.py` | 2 nuevos endpoints + logging auto-match |

---

## Restricciones

- El subquery de conteo solo corre para comprobantes en estado PENDIENTE o PARCIALMENTE_FACTURADO (los demás no pueden recibir match).
- La búsqueda manual en el modal usa el mismo criterio relajado del endpoint, no accede a la BD por cada keystroke — hay debounce de 400ms.
- `_procesar_match_unico` ya maneja la transacción, el upload a SharePoint y el logging de errores. No se duplica.
- El id `comprobante-row-{id}` en el `<tr>` es el único cambio estructural en `row_comprobante.html`.
