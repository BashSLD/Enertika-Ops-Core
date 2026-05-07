# SAT + Compras Integración Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar fricción entre `/compras/ui` y `/compras/sat/ui` añadiendo visibilidad de candidatos SAT directamente en la tabla de comprobantes, con modal de vinculación y búsqueda manual.

**Architecture:** Se agrega un subquery correlacionado en `get_comprobantes_filtered` que cuenta CFDIs SAT candidatos por comprobante. Un badge en cada fila activa un modal nuevo (`sat_candidatos_modal.html`) que lista candidatos y permite match sin salir de `/compras/ui`. Dos nuevos endpoints en `sat_router.py` manejan la carga del modal y la confirmación del match, reutilizando `_procesar_match_unico`.

**Tech Stack:** FastAPI + asyncpg + Jinja2 + HTMX + Alpine.js + Tailwind CSS

---

## File Map

| Archivo | Acción |
|---------|--------|
| `templates/compras/partials/sat_inbox_content.html` | Modificar — eliminar card header |
| `templates/compras/partials/sat_inbox_table.html` | Modificar — agregar columna Tipo |
| `templates/compras/partials/content.html` | Modificar — eliminar btn Excel header + agregar div modal container |
| `templates/compras/partials/tabla_comprobantes.html` | Modificar — agregar ícono Excel junto a Filtros |
| `templates/compras/partials/row_comprobante.html` | Modificar — renombrar id tr + badge SAT |
| `templates/compras/partials/sat_candidatos_modal.html` | Crear — modal de candidatos SAT |
| `modules/compras/db_service.py` | Modificar — subquery `sat_candidatos_count` + `get_comprobante_fila` |
| `modules/compras/sat_db_service.py` | Modificar — `buscar_candidatos_para_comprobante` + `contar_candidatos_para_comprobante` |
| `modules/compras/sat_router.py` | Modificar — 2 endpoints nuevos + logging auto-match |

---

## Task 1: UI quick wins — SAT inbox

**Files:**
- Modify: `templates/compras/partials/sat_inbox_content.html:18-28`
- Modify: `templates/compras/partials/sat_inbox_table.html:51-58`

- [ ] **Step 1: Eliminar el card header de sat_inbox_content.html**

Eliminar el bloque `<div class="rounded-xl border ...">` que contiene el badge "Compras SAT", el `<h2>Inbox SAT — ISA</h2>` y el párrafo descriptivo. El archivo quedaría:

```html
<div class="space-y-6 p-6" id="sat-inbox-root"
     x-data="{ selectedCount: 0 }"
     @selection-changed.window="selectedCount = $event.detail">
  <div id="mobile-actions-template" style="display:none"></div>
  <script>
  (function() {
      var tmpl = document.getElementById('mobile-actions-template');
      var slot = document.getElementById('mobile-module-actions-slot');
      if (!slot || !tmpl) return;
      slot.innerHTML = '';
      Array.from(tmpl.children).forEach(function(child) { slot.appendChild(child.cloneNode(true)); });
      if (typeof htmx !== 'undefined') htmx.process(slot);
      var sep = document.getElementById('mobile-actions-separator');
      if (sep) sep.classList.toggle('hidden', slot.children.length === 0);
  })();
  </script>

  <div class="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
```

- [ ] **Step 2: Agregar columna Tipo en sat_inbox_table.html**

Después de `{{ sort_th('moneda', 'Moneda', 'text-left') }}` y antes de `<th class="px-4 py-3 text-left font-medium text-gray-500">Estado</th>`, agregar:

```html
<th class="px-4 py-3 text-left font-medium text-gray-500">Tipo</th>
```

En el cuerpo de la tabla, después de `<td class="px-4 py-3 text-gray-500">{{ item.moneda }}</td>` agregar:

```html
<td class="px-4 py-3">
  {% set tipo_labels = {
      'NORMAL': ('Factura', 'bg-green-100 text-green-800'),
      'ANTICIPO': ('Anticipo', 'bg-orange-100 text-orange-800'),
      'CIERRE_ANTICIPO': ('Cierre Anticipo', 'bg-blue-100 text-blue-800'),
      'PAGO': ('Comp. Pago', 'bg-cyan-100 text-cyan-800'),
      'NOTA_CREDITO': ('Nota Crédito', 'bg-purple-100 text-purple-800'),
  } %}
  {% set tipo = item.tipo_detectado or 'NORMAL' %}
  {% set label, cls = tipo_labels.get(tipo, ('Factura', 'bg-green-100 text-green-800')) %}
  <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {{ cls }}">
    {{ label }}
  </span>
</td>
```

- [ ] **Step 3: Verificar en browser**

Navegar a `/compras/sat/ui`. Confirmar:
- El header card con "Inbox SAT — ISA" ya no aparece
- La tabla tiene columna "Tipo" con badges de colores

- [ ] **Step 4: Commit**

```bash
git add templates/compras/partials/sat_inbox_content.html templates/compras/partials/sat_inbox_table.html
git commit -m "feat(compras/sat): eliminar header redundante y agregar columna tipo CFDI"
```

---

## Task 2: Mover botón Excel al área de filtros

**Files:**
- Modify: `templates/compras/partials/content.html:120-131`
- Modify: `templates/compras/partials/tabla_comprobantes.html:27-50`

- [ ] **Step 1: Eliminar botón Excel del header desktop en content.html**

Eliminar el bloque completo:
```html
                <!-- Botón Export Excel -->
                <a id="export-excel-btn"
                    href="/compras/export-excel?estatus=SIN_COMPLETAR&fecha_inicio={{ filtros.fecha_inicio }}&fecha_fin={{ filtros.fecha_fin }}"
                    class="compras-action-btn ripple-effect bg-green-600 hover:bg-green-700 text-white font-bold py-2 px-2.5 text-sm rounded-lg shadow transition-transform hover:scale-105"
                    aria-label="Exportar Excel">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24"
                        stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <span class="compras-action-label">Exportar Excel</span>
                </a>
```

- [ ] **Step 2: Agregar ícono Excel junto al botón Filtros en tabla_comprobantes.html**

El `<div class="flex items-center gap-2">` que contiene la paginación y el botón Filtros. Agregar después del botón Filtros (antes del cierre del `</div>`):

```html
            <a id="export-excel-btn"
               href="/compras/export-excel?estatus=SIN_COMPLETAR"
               title="Exportar Excel"
               class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-gray-300 bg-white hover:bg-gray-50 text-xs font-semibold text-gray-700 transition-colors">
              <svg class="w-4 h-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
              </svg>
              Excel
            </a>
```

Nota: el href ya no incluye `fecha_inicio`/`fecha_fin` del contexto del header porque este template no tiene esos valores de filtros en scope. El endpoint `/compras/export-excel` funciona sin esos parámetros (exporta todos los SIN_COMPLETAR).

- [ ] **Step 3: Verificar en browser**

Navegar a `/compras/ui`. Confirmar:
- El header ya no tiene el botón verde de Excel
- Junto al botón "Filtros" aparece un ícono de descarga "Excel"
- El link de Excel funciona y descarga el archivo

- [ ] **Step 4: Commit**

```bash
git add templates/compras/partials/content.html templates/compras/partials/tabla_comprobantes.html
git commit -m "feat(compras): mover botón Excel del header a zona de filtros"
```

---

## Task 3: Logging en Auto-Match

**Files:**
- Modify: `modules/compras/sat_router.py:487-540`

- [ ] **Step 1: Agregar logs INFO en confirm_auto_match**

En `confirm_auto_match`, después del check `if not matches:` (que retorna early), agregar antes del loop `for match_str in matches:`:

```python
    logger.info("Auto-match iniciado: %d pares recibidos", len(matches))
```

Dentro del bloque `try` del loop, después de `await _procesar_match_unico(...)`:

```python
            logger.info("Auto-match OK: inbox=%s comprobante=%s", inbox_id_str, comprobante_id_str)
```

Después del loop, antes de `msg = f"{procesados}..."`:

```python
    logger.info("Auto-match completado: %d exitosos, %d errores de %d pares", procesados, errores, len(matches))
```

El bloque completo del loop queda:

```python
    logger.info("Auto-match iniciado: %d pares recibidos", len(matches))
    for match_str in matches:
        try:
            inbox_id_str, comprobante_id_str = match_str.split("|")
            inbox_id = UUID(inbox_id_str)
            comprobante_id = UUID(comprobante_id_str)
            await _procesar_match_unico(conn, inbox_id, comprobante_id, user_id)
            logger.info("Auto-match OK: inbox=%s comprobante=%s", inbox_id_str, comprobante_id_str)
            procesados += 1
        except (ValueError, asyncpg.PostgresError) as e:
            logger.warning("Error en auto-match para %s: %s", match_str, e)
            errores += 1
        except Exception:
            logger.exception("Error inesperado en auto-match para %s", match_str)
            errores += 1

    logger.info("Auto-match completado: %d exitosos, %d errores de %d pares", procesados, errores, len(matches))
```

- [ ] **Step 2: Commit**

```bash
git add modules/compras/sat_router.py
git commit -m "fix(compras/sat): agregar logging INFO en auto-match para diagnostico"
```

---

## Task 4: DB — subquery sat_candidatos_count + funciones SAT candidatos

**Files:**
- Modify: `modules/compras/db_service.py:62-159`
- Modify: `modules/compras/sat_db_service.py` (agregar al final)

- [ ] **Step 1: Agregar sat_candidatos_count al SELECT de get_comprobantes_filtered**

En `db_service.py`, en la variable `base_query` dentro de `get_comprobantes_filtered`, agregar el subquery como último campo del SELECT, después de `count_xml`:

```python
        base_query = """
            SELECT
                c.id_comprobante,
                c.fecha_pago,
                c.beneficiario_orig,
                c.monto,
                c.moneda,
                c.estatus,
                c.uuid_factura,
                c.monto_facturado,
                c.monto_remanente,
                c.motivo_cierre,
                c.created_at,
                c.id_proveedor,
                c.id_zona,
                c.id_proyecto,
                c.id_categoria,
                c.tipo_factura,
                c.es_anticipo,
                u.nombre as comprador_nombre,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                z.nombre as zona_nombre,
                pr.proyecto_id_estandar as proyecto_nombre,
                cat.nombre as categoria_nombre,
                (SELECT COUNT(*)
                 FROM tb_documentos_attachments da
                 WHERE da.activo = true
                 AND da.metadata->>'id_comprobante' = c.id_comprobante::text
                 AND da.origen_slug = 'comprobante_pago'
                ) as count_pdf,
                (SELECT COUNT(*)
                 FROM tb_documentos_attachments da
                 WHERE da.activo = true
                 AND da.metadata->>'id_comprobante' = c.id_comprobante::text
                 AND da.origen_slug = 'factura_xml'
                ) as count_xml,
                (SELECT COUNT(*)
                 FROM tb_sat_inbox i
                 WHERE i.estado = 'pendiente'
                   AND c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO', 'ANTICIPO')
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
                ) as sat_candidatos_count
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            LEFT JOIN tb_proveedores p ON c.id_proveedor = p.id_proveedor
            LEFT JOIN tb_cat_zonas_compra z ON c.id_zona = z.id
            LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
            LEFT JOIN tb_cat_categorias_compra cat ON c.id_categoria = cat.id
            WHERE 1=1
        """
```

- [ ] **Step 2: Agregar get_comprobante_fila en db_service.py**

Después de `get_comprobante_by_id` (línea ~178), agregar nuevo método en la clase `ComprasDBService`:

```python
    async def get_comprobante_fila(self, conn, id_comprobante: UUID) -> Optional[dict]:
        """Comprobante con todos los campos de la fila de tabla, incluido sat_candidatos_count."""
        row = await conn.fetchrow("""
            SELECT
                c.id_comprobante, c.fecha_pago, c.beneficiario_orig, c.monto, c.moneda,
                c.estatus, c.uuid_factura, c.monto_facturado, c.monto_remanente,
                c.tipo_factura, c.es_anticipo, c.id_proveedor, c.id_zona,
                c.id_proyecto, c.id_categoria,
                u.nombre as comprador_nombre,
                p.razon_social as proveedor_nombre,
                p.rfc as proveedor_rfc,
                z.nombre as zona_nombre,
                pr.proyecto_id_estandar as proyecto_nombre,
                cat.nombre as categoria_nombre,
                (SELECT COUNT(*) FROM tb_documentos_attachments da
                 WHERE da.activo = true
                   AND da.metadata->>'id_comprobante' = c.id_comprobante::text
                   AND da.origen_slug = 'comprobante_pago') as count_pdf,
                (SELECT COUNT(*) FROM tb_documentos_attachments da
                 WHERE da.activo = true
                   AND da.metadata->>'id_comprobante' = c.id_comprobante::text
                   AND da.origen_slug = 'factura_xml') as count_xml,
                (SELECT COUNT(*) FROM tb_sat_inbox i
                 WHERE i.estado = 'pendiente'
                   AND c.estatus IN ('PENDIENTE', 'PARCIALMENTE_FACTURADO', 'ANTICIPO')
                   AND ABS(i.total - c.monto) <= 1.00
                   AND (
                       i.nombre_emisor ILIKE '%' || c.beneficiario_orig || '%'
                       OR c.beneficiario_orig ILIKE '%' || i.nombre_emisor || '%'
                       OR EXISTS (SELECT 1 FROM tb_proveedores p2
                                  WHERE p2.id_proveedor = c.id_proveedor
                                    AND p2.rfc = i.rfc_emisor)
                   )) as sat_candidatos_count
            FROM tb_comprobantes_pago c
            LEFT JOIN tb_usuarios u ON c.capturado_por_id = u.id_usuario
            LEFT JOIN tb_proveedores p ON c.id_proveedor = p.id_proveedor
            LEFT JOIN tb_cat_zonas_compra z ON c.id_zona = z.id
            LEFT JOIN tb_proyectos_gate pr ON c.id_proyecto = pr.id_proyecto
            LEFT JOIN tb_cat_categorias_compra cat ON c.id_categoria = cat.id
            WHERE c.id_comprobante = $1
        """, id_comprobante)
        return dict(row) if row else None
```

- [ ] **Step 3: Agregar funciones en sat_db_service.py**

Al final de `sat_db_service.py`, agregar:

```python
async def buscar_candidatos_para_comprobante(
    conn: asyncpg.Connection,
    monto: float,
    beneficiario_orig: str,
    proveedor_rfc: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict]:
    """Busca SAT inbox items candidatos para vincular a un comprobante.

    Sin q: criterio relajado — monto ±1.00 + nombre ILIKE o RFC.
    Con q: busca en todos los pendientes por nombre/RFC que contengan q.
    """
    if q:
        rows = await conn.fetch(
            """
            SELECT id, uuid_cfdi, rfc_emisor, nombre_emisor, total, moneda,
                   fecha_cfdi, tipo_detectado
            FROM tb_sat_inbox
            WHERE estado = 'pendiente'
              AND (
                  nombre_emisor ILIKE '%' || $1 || '%'
                  OR rfc_emisor ILIKE '%' || $1 || '%'
              )
            ORDER BY fecha_cfdi DESC
            LIMIT 50
            """,
            q,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, uuid_cfdi, rfc_emisor, nombre_emisor, total, moneda,
                   fecha_cfdi, tipo_detectado
            FROM tb_sat_inbox
            WHERE estado = 'pendiente'
              AND ABS(total - $1) <= 1.00
              AND (
                  nombre_emisor ILIKE '%' || $2 || '%'
                  OR $2 ILIKE '%' || nombre_emisor || '%'
                  OR ($3::text IS NOT NULL AND rfc_emisor = $3)
              )
            ORDER BY ABS(total - $1) ASC, fecha_cfdi DESC
            """,
            monto,
            beneficiario_orig,
            proveedor_rfc,
        )
    return [dict(r) for r in rows]
```

También necesita el import de `Optional` si no existe. Verificar el encabezado de `sat_db_service.py` y agregar `from typing import Optional` si falta.

- [ ] **Step 4: Verificar que el import Optional existe en sat_db_service.py**

```bash
grep -n "from typing import" modules/compras/sat_db_service.py
```

Si no existe, agregar al inicio del archivo:
```python
from typing import Optional
```

- [ ] **Step 5: Commit**

```bash
git add modules/compras/db_service.py modules/compras/sat_db_service.py
git commit -m "feat(compras): agregar sat_candidatos_count en query comprobantes y funciones de búsqueda SAT"
```

---

## Task 5: Badge SAT en filas + contenedor modal

**Files:**
- Modify: `templates/compras/partials/row_comprobante.html:3`
- Modify: `templates/compras/partials/row_comprobante.html` (sección de acciones/adjuntos)
- Modify: `templates/compras/partials/content.html:243-250`

- [ ] **Step 1: Cambiar id del tr en row_comprobante.html**

Línea 3, cambiar:
```html
<tr id="row-{{ comprobante.id_comprobante }}" class="hover:bg-gray-50 transition-colors">
```
por:
```html
<tr id="comprobante-row-{{ comprobante.id_comprobante }}" class="hover:bg-gray-50 transition-colors">
```

- [ ] **Step 2: Agregar badge SAT en la columna de adjuntos**

En `row_comprobante.html`, localizar la celda de adjuntos (`<!-- Adjuntos -->`). Dentro del `<div class="flex items-center justify-center gap-2">`, al final (después del ícono XML), agregar:

```html
            <!-- Badge SAT candidatos -->
            {% if comprobante.sat_candidatos_count and comprobante.sat_candidatos_count > 0 %}
            <button
                hx-get="/compras/sat/comprobante/{{ comprobante.id_comprobante }}/candidatos"
                hx-target="#sat-candidatos-modal-container"
                hx-swap="innerHTML"
                title="{{ comprobante.sat_candidatos_count }} CFDI(s) del SAT sin vincular"
                class="inline-flex items-center gap-1 rounded-full bg-teal-100 px-2 py-0.5 text-xs font-semibold text-teal-800 hover:bg-teal-200 transition-colors">
                <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
                SAT · {{ comprobante.sat_candidatos_count }}
            </button>
            {% endif %}
```

- [ ] **Step 3: Agregar div contenedor para modal en content.html**

Después de `<div id="xml-staging-modal-container"></div>` y antes del cierre `</div>` final, agregar:

```html
    <!-- Container para modal de candidatos SAT (se carga desde badge en filas) -->
    <div id="sat-candidatos-modal-container"></div>
```

- [ ] **Step 4: Verificar en browser**

Navegar a `/compras/ui`. Si hay comprobantes con SAT candidatos, el badge "SAT · N" aparece en su fila. Si no hay candidatos en el inbox pendiente, el badge no aparece (correcto).

Para forzar la prueba: verificar que la query se ejecuta sin error revisando los logs del servidor al cargar `/compras/comprobantes`.

- [ ] **Step 5: Commit**

```bash
git add templates/compras/partials/row_comprobante.html templates/compras/partials/content.html
git commit -m "feat(compras): agregar badge SAT por fila con count de candidatos pendientes"
```

---

## Task 6: Endpoints nuevos en sat_router.py

**Files:**
- Modify: `modules/compras/sat_router.py`

- [ ] **Step 1: Agregar imports necesarios en sat_router.py**

Verificar que `get_db_service` está importado. Al inicio del archivo, en la sección de imports de módulos internos, agregar si no existe:

```python
from modules.compras.db_service import get_db_service
```

- [ ] **Step 2: Agregar endpoint GET candidatos**

Al final de `sat_router.py`, agregar:

```python
@router.get("/comprobante/{id_comprobante}/candidatos", response_class=HTMLResponse)
async def get_candidatos_sat(
    request: Request,
    id_comprobante: UUID,
    q: Optional[str] = None,
    conn=Depends(get_db_connection),
    _=require_module_access("compras", "editor"),
):
    db_svc = get_db_service()
    comprobante = await db_svc.get_comprobante_by_id(conn, id_comprobante)
    if not comprobante:
        return templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "Comprobante no encontrado", "type": "error"},
            status_code=404,
            headers={"HX-Reswap": "none"},
        )
    candidatos = await sat_db_service.buscar_candidatos_para_comprobante(
        conn,
        monto=float(comprobante["monto"]),
        beneficiario_orig=comprobante["beneficiario_orig"] or "",
        proveedor_rfc=comprobante.get("proveedor_rfc"),
        q=q,
    )
    return templates.TemplateResponse(
        request,
        "compras/partials/sat_candidatos_modal.html",
        {
            "comprobante": comprobante,
            "candidatos": candidatos,
            "busqueda": q or "",
        },
    )
```

También agregar `Optional` al import de `typing` si no está (revisar imports al inicio del archivo).

- [ ] **Step 3: Agregar endpoint POST match-desde-comprobante**

Continuando en `sat_router.py`, agregar:

```python
@router.post("/inbox/{inbox_id}/match-desde-comprobante", response_class=HTMLResponse)
async def match_desde_comprobante(
    request: Request,
    inbox_id: UUID,
    comprobante_id: UUID = Form(...),
    conn=Depends(get_db_connection),
    user=Depends(get_current_user_context),
    _=require_module_access("compras", "editor"),
):
    db_svc = get_db_service()
    user_id = user["user_db_id"]
    try:
        await _procesar_match_unico(conn, inbox_id, comprobante_id, user_id)
    except (ValueError, asyncpg.PostgresError) as e:
        logger.warning("match-desde-comprobante error inbox=%s comp=%s: %s", inbox_id, comprobante_id, e)
        toast_html = templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": str(e), "type": "error"},
        ).body.decode("utf-8")
        return HTMLResponse(content=toast_html)
    except Exception:
        logger.exception("match-desde-comprobante error inesperado inbox=%s comp=%s", inbox_id, comprobante_id)
        toast_html = templates.TemplateResponse(
            request,
            "shared/toast.html",
            {"message": "Error inesperado al procesar el match.", "type": "error"},
        ).body.decode("utf-8")
        return HTMLResponse(content=toast_html)

    comprobante = await db_svc.get_comprobante_fila(conn, comprobante_id)
    row_html = templates.TemplateResponse(
        request,
        "compras/partials/row_comprobante.html",
        {"comprobante": comprobante},
    ).body.decode("utf-8")
    row_oob = row_html.replace(
        f'id="comprobante-row-{comprobante_id}"',
        f'id="comprobante-row-{comprobante_id}" hx-swap-oob="outerHTML"',
        1,
    )
    toast_html = templates.TemplateResponse(
        request,
        "shared/toast.html",
        {"message": "CFDI vinculado correctamente", "type": "success"},
    ).body.decode("utf-8")
    close_modal = '<div id="sat-candidatos-modal-container" hx-swap-oob="innerHTML"></div>'
    return HTMLResponse(content=row_oob + toast_html + close_modal)
```

- [ ] **Step 4: Verificar imports en sat_router.py**

Confirmar que al inicio del archivo existen:
```python
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, Query
from modules.compras.db_service import get_db_service
```

Si `Query` no está en el import de fastapi (para el param `q`), agregarlo. `Optional` viene de `typing`.

- [ ] **Step 5: Commit**

```bash
git add modules/compras/sat_router.py
git commit -m "feat(compras/sat): endpoints candidatos-por-comprobante y match-desde-comprobante"
```

---

## Task 7: Template sat_candidatos_modal.html

**Files:**
- Create: `templates/compras/partials/sat_candidatos_modal.html`

- [ ] **Step 1: Crear el template**

```html
<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
     x-data="{ selectedInboxId: '', busqueda: '{{ busqueda | e }}' }"
     x-init="$el.addEventListener('click', e => { if (e.target === $el) document.getElementById('sat-candidatos-modal-container').innerHTML = '' })">
  <div class="bg-white rounded-xl shadow-xl w-full max-w-xl mx-4 flex flex-col max-h-[90dvh]">

    <!-- Header -->
    <div class="px-6 py-4 border-b flex items-center justify-between">
      <div>
        <h3 class="font-semibold text-gray-900">CFDIs SAT candidatos</h3>
        <p class="text-xs text-gray-500 mt-0.5">
          {{ comprobante.proveedor_nombre or comprobante.beneficiario_orig }}
          — ${{ '{:,.2f}'.format(comprobante.monto or 0) }} {{ comprobante.moneda }}
        </p>
      </div>
      <button type="button"
        onclick="document.getElementById('sat-candidatos-modal-container').innerHTML = ''"
        class="text-gray-400 hover:text-gray-600">
        <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>

    <!-- Body -->
    <div class="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-4">

      <!-- Búsqueda manual -->
      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">
          {% if not candidatos %}Sin coincidencias automáticas. Busca manualmente:
          {% else %}Buscar otro CFDI:{% endif %}
        </label>
        <input type="text"
          placeholder="Nombre emisor o RFC..."
          x-model="busqueda"
          hx-get="/compras/sat/comprobante/{{ comprobante.id_comprobante }}/candidatos"
          hx-trigger="input delay:400ms"
          hx-target="#sat-candidatos-modal-container"
          hx-swap="innerHTML"
          :name="'q'"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500">
      </div>

      <!-- Lista de candidatos -->
      <div id="sat-candidatos-lista">
        {% set tipo_labels = {
            'NORMAL': ('Factura', 'bg-green-100 text-green-800'),
            'ANTICIPO': ('Anticipo', 'bg-orange-100 text-orange-800'),
            'CIERRE_ANTICIPO': ('Cierre Anticipo', 'bg-blue-100 text-blue-800'),
            'PAGO': ('Comp. Pago', 'bg-cyan-100 text-cyan-800'),
            'NOTA_CREDITO': ('Nota Crédito', 'bg-purple-100 text-purple-800'),
        } %}
        {% if candidatos %}
        <div class="space-y-2">
          {% for c in candidatos %}
          {% set tipo = c.tipo_detectado or 'NORMAL' %}
          {% set label, cls = tipo_labels.get(tipo, ('Factura', 'bg-green-100 text-green-800')) %}
          <label class="flex items-start gap-3 rounded-lg border p-3 cursor-pointer hover:bg-gray-50 transition-colors"
                 :class="selectedInboxId === '{{ c.id }}' ? 'border-teal-400 bg-teal-50' : 'border-gray-200'">
            <input type="radio" name="inbox_id_sel" value="{{ c.id }}"
                   x-model="selectedInboxId"
                   class="mt-0.5 text-teal-600 focus:ring-teal-500">
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between gap-2">
                <span class="text-sm font-medium text-gray-900 truncate">{{ c.nombre_emisor or '—' }}</span>
                <span class="text-sm font-bold text-gray-900 whitespace-nowrap">
                  ${{ '{:,.2f}'.format(c.total or 0) }} {{ c.moneda }}
                </span>
              </div>
              <div class="flex items-center gap-2 mt-1">
                <span class="font-mono text-xs text-gray-500">{{ c.rfc_emisor }}</span>
                <span class="text-xs text-gray-400">{{ c.fecha_cfdi or '—' }}</span>
                <span class="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium {{ cls }}">
                  {{ label }}
                </span>
              </div>
              <div class="text-[10px] text-gray-400 mt-0.5 font-mono" title="{{ c.uuid_cfdi }}">
                {{ c.uuid_cfdi[:8] if c.uuid_cfdi else '—' }}...
              </div>
            </div>
          </label>
          {% endfor %}
        </div>
        {% else %}
        <p class="text-sm text-gray-400 text-center py-4">
          No se encontraron CFDIs en el inbox.
        </p>
        {% endif %}
      </div>

    </div>

    <!-- Footer -->
    <div class="px-6 py-4 border-t flex justify-end gap-3">
      <button type="button"
        onclick="document.getElementById('sat-candidatos-modal-container').innerHTML = ''"
        class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">
        Cancelar
      </button>
      <button type="button"
        :disabled="!selectedInboxId"
        @click="
          if (!selectedInboxId) return;
          const formData = new FormData();
          formData.append('comprobante_id', '{{ comprobante.id_comprobante }}');
          htmx.ajax('POST',
            '/compras/sat/inbox/' + selectedInboxId + '/match-desde-comprobante',
            { target: 'body', swap: 'none', values: Object.fromEntries(formData) }
          );
        "
        class="px-4 py-2 text-sm font-medium text-white bg-teal-600 rounded-lg hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed">
        Confirmar vinculación
      </button>
    </div>

  </div>
</div>
```

**Nota sobre el botón Confirmar:** Usa `htmx.ajax` directamente porque el `inbox_id` viene del radio button seleccionado (valor dinámico Alpine). El target `'body'` con `swap: 'none'` permite que HTMX procese las respuestas OOB (row update + toast + close modal) sin swapear nada extra.

- [ ] **Step 2: Verificar en browser**

1. Navegar a `/compras/ui`
2. Si hay un comprobante con badge SAT, hacer click en él
3. El modal debe abrirse con la lista de candidatos
4. Seleccionar uno y confirmar → la fila se actualiza, el badge desaparece o disminuye, aparece toast de éxito
5. Si no hay candidatos, el campo de búsqueda aparece prominente — escribir un nombre/RFC y verificar que la lista se actualiza

- [ ] **Step 3: Commit**

```bash
git add templates/compras/partials/sat_candidatos_modal.html
git commit -m "feat(compras): modal de candidatos SAT para vincular desde comprobantes"
```

---

## Self-Review

**Spec coverage:**
- ✅ Eliminar header SAT inbox → Task 1
- ✅ Columna Tipo en SAT inbox → Task 1
- ✅ Mover Excel a filtros → Task 2
- ✅ Logging auto-match → Task 3
- ✅ Subquery sat_candidatos_count → Task 4
- ✅ Badge SAT en fila → Task 5
- ✅ Modal contenedor → Task 5
- ✅ Endpoint GET candidatos → Task 6
- ✅ Endpoint POST match-desde-comprobante → Task 6
- ✅ Template sat_candidatos_modal.html → Task 7
- ✅ Búsqueda manual con debounce → Task 7 (campo de texto con hx-trigger)
- ✅ OOB: row update + toast + close modal tras match → Task 6 + Task 7

**Placeholders:** Ninguno detectado. Todos los pasos tienen código completo.

**Type consistency:**
- `buscar_candidatos_para_comprobante` definida en Task 4, usada en Task 6 ✅
- `get_comprobante_fila` definida en Task 4, usada en Task 6 ✅
- `comprobante-row-{id}` en Task 5 (template) y Task 6 (OOB replace) ✅
- `#sat-candidatos-modal-container` en Task 5 (content.html) y Task 7 (cierre OOB) ✅
- `selectedInboxId` Alpine en Task 7, usado en el botón confirmar del mismo task ✅
