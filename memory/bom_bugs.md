# BOM — Bugs e Inconsistencias (2026-03-08)

Estado: **BATCH CORREGIDO** — 11 bugs + 4 nuevos resueltos en 2026-03-08.

Archivos principales:
- `core/bom/router.py`
- `core/bom/service.py`
- `core/bom/db_service.py`
- `core/bom/schemas.py`
- Templates: `templates/bom/partials/`

---

## RESUELTOS (2026-03-08)

| Bug | Fix aplicado |
|-----|-------------|
| BUG-1 | `jefe_construccion` y `coordinador_obra` son roles distintos — ambos coexisten. `jefe_construccion_nombre` agregado a `BomRead` schema y mostrado en `header_estatus.html` |
| BUG-2 | `rechazar_ing()` limpia `fecha_aprobacion_ing=None`; `rechazar_const()` limpia `fecha_aprobacion_const=None`; `devolver_a_borrador()` limpia ambos |
| BUG-3 | `editar_item()` valida `cant_recibida > cant_total` → ValueError |
| BUG-4 | `hx-disabled-elt="find button[type='submit']"` en ambos forms (agregar + editar item); `disabled:opacity-60 disabled:cursor-not-allowed` en botones |
| BUG-5 | `modal_item.html` — eliminado `role != 'ADMIN'` de todas las condiciones disabled; ahora solo obedece `area_editor` |
| BUG-6 | Mensaje claro cuando Compras intenta agregar items ("Solo Ingeniería y Construcción pueden agregar items…") |
| BUG-7 | `enviar-const` cambiado de `require_module_access("ingenieria","editor")` a `require_manager_access("ingenieria")` |
| BUG-9 | Excel export: `precio = float(item.get('precio_unitario') or 0)` safe conversion |
| BUG-11 | `jefe_construccion: Optional[UUID]` + `jefe_construccion_nombre: Optional[str]` agregados a `BomRead` |
| NEW-cantidad | `agregar_item()` valida `cantidad <= 0` → ValueError |
| NEW-precio | `agregar_item()` y `editar_item()` validan `precio_unitario < 0` → ValueError |
| NEW-porcentaje | `row_item.html`: `[pct, 100]|min` en texto de porcentaje (evita mostrar >100%) |
| NEW-rbac-admin | Inconsistencia resuelta via BUG-5: `area_editor` es la única fuente de verdad para edición |

## PENDIENTES / NO RESUELTOS

| Bug | Motivo |
|-----|--------|
| BUG-8 | Indicador visual `required` en textarea de rechazo — bajo impacto, pendiente |
| BUG-10 | Documentación de semántica `get_bom_by_proyecto()` — solo doc |

---

## Workflow actual de estados (actualizado 2026-03-18 — post Fase A)
```
BORRADOR → EN_REVISION_ING → APROBADO_ING → EN_REVISION_OBRA → APROBADO_OBRA
               ↓ (rechazar_ing → BORRADOR)                         ↓
                                              EN_REVISION_CONST → APROBADO_CONST → EN_REVISION_FINAL → APROBADO_FINAL
```
Ver `memory/bom_roadmap_v2.md` para el flujo completo de 4 aprobadores.

## Permisos por área (vigente)
- `area_editor = 'ingenieria'` → edita en `BORRADOR` solamente
- `area_editor = 'construccion'` → edita sus campos en `APROBADO_ING / EN_REVISION_CONST / APROBADO_CONST`
- `area_editor = 'compras'` → edita proveedor/precio/entrega en los mismos estados que construccion
- ADMIN del sistema → `area_editor = 'ingenieria'` (mismos permisos que editor de ing)
- Compras NO puede agregar ni eliminar items (solo editar campos propios)

---

## ROADMAP PENDIENTE (acordar antes de implementar — 2026-03-08)

Ver `memory/bom_roadmap_v2.md` para el análisis completo de:
1. Edición durante aprobaciones (EN_REVISION_ING / EN_REVISION_CONST)
2. UX modal por departamento
3. Edición masiva (bulk edit)
4. Aprobador final (jefe de todos)
5. Suplencias por ausencia
