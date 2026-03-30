---
name: levantamientos_ui_mobile_icons
description: Problema de visibilidad de iconos en botones principales en móviles — Levantamientos y otros módulos
type: project
---

# Problema: Iconos Invisibles en Móviles (Levantamientos)

## Descripción del Problema
En dispositivos móviles, los iconos de algunos botones principales no se ven (aparecen en negro sobre fondo oscuro, o no cargan). Reportado en la sesión 2026-03-24 al revisar el módulo Levantamientos.

## Causa Raíz Identificada
Dos causas posibles coexisten:

### 1. Íconos sin clase de color explícita
En `visita_campo_levantamientos.html:28` (y posiblemente otros templates), el ícono de calendario usa:
```html
<i class="fas fa-calendar-day" style="font-size:9px;"></i>
```
No tiene clase de color Tailwind (`text-*`). El color heredado del padre puede ser negro o indefinido en modo oscuro/mobile, haciéndolo invisible.

**Fix:** Agregar clase de color explícita: `class="fas fa-calendar-day text-blue-400" style="font-size:9px;"`.

### 2. Botones con SVG inline sin stroke explícito en mobile
Algunos botones en el Kanban (`kanban.html`) y modales usan SVG con `stroke="currentColor"`. Si el color CSS computado es transparente o el modo de renderizado móvil difiere, el ícono desaparece.

**Patrón afectado:** Botones de acción principales del kanban mobile — el menú "Acciones" colapsable en mobile (líneas 6-60 del kanban.html) usa SVGs inline con colores correctos (text-white), eso debería estar bien.

### 3. Botón "X" para cerrar modales individuales (viaticos_modal)
El botón X de cierre del modal de viáticos individual no se percibe — está sobre fondo oscuro con color gris claro. Fix: usar `text-slate-400 hover:text-white`.

## Archivos Afectados

| Archivo | Línea aprox | Problema |
|---------|-------------|---------|
| `templates/levantamientos/partials/visita_campo_levantamientos.html` | 28 | `<i class="fas fa-calendar-day">` sin color |
| `templates/levantamientos/modals/visita_campo_modal.html` | header | Botón volver (ya corregido sesión anterior) |
| `templates/levantamientos/visita_campo_detalle_content.html` | header | Botón volver (ya corregido sesión anterior) |
| `templates/levantamientos/modals/viaticos_modal.html` | close btn | X de cierre poco visible |
| `templates/levantamientos/visita_campo_crear_content.html` | calendar inputs | Iconos de calendario son negros (`text-gray-500`/`text-black`) sobre fondo gris — poca visibilidad |

## Estrategia de Fix

1. **Íconos FontAwesome sin color:** Siempre agregar `text-{color}` explícito — nunca depender del color heredado.
2. **Íconos de calendario en inputs:** Cambiar de `text-gray-500` / sin clase a `text-blue-400` o `text-slate-400` para mejor contraste.
3. **Botones X de cierre en modales oscuros:** Usar `text-slate-400 hover:text-white transition-colors` — no `text-slate-600` que se pierde en fondos `bg-slate-800/bg-slate-900`.
4. **Mobile-specific:** En el kanban mobile (menú Acciones colapsable), los botones ya tienen `text-white` en SVGs — OK. Verificar si hay algún ícono suelto fuera del menú Acciones.

## Pendiente de Implementar
- [ ] Fix `visita_campo_levantamientos.html:28` — agregar `text-blue-400` al ícono fa-calendar-day
- [ ] Fix inputs de fechas en `visita_campo_crear_content.html` y `visita_campo_detalle_content.html` — cambiar color de iconos de calendario
- [ ] Fix botón X del `viaticos_modal.html` — mejorar contraste
- [ ] Auditoría rápida de modales del módulo levantamientos: todo botón X sobre fondo oscuro debe tener `text-slate-400 hover:text-white`

## Notas
- El problema de visibilidad del botón "Volver" en `visita_campo_crear_content.html` y `visita_campo_detalle_content.html` ya fue corregido en sesión 2026-03-24 (se cambió a pill button visible).
- El botón de "lápiz" para editar periodo y el botón "Sacar" también ya fueron corregidos en esa sesión.
- Este documento cubre los ítems de UI pendientes que aún no se han tocado.
