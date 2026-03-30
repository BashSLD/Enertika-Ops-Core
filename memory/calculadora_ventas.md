---
name: calculadora_ventas
description: Calculadora de ventas FV compartida entre Comercial y Simulacion — TC, costo sistema, numero de paneles
type: project
---

## Feature: Calculadora de Ventas (modal compartido)

Implementada 2026-03-24. Modal Alpine.js reactivo para estimacion rapida de sistema fotovoltaico.

### Archivos clave
- **Template:** `templates/shared/modals/calculadora_ventas.html`
- **Endpoint:** `modules/shared/router.py` → `GET /shared/partials/calculadora-ventas?modulo=xxx`
- **Registro:** `main.py` — `shared_router`

### Botones de acceso
- `templates/comercial/tabs.html` — desktop (icono solo + tooltip) + mobile (dropdown con texto)
- `templates/simulacion/tabs.html` — misma estructura

### Patron HTMX del boton
```html
hx-get="/shared/partials/calculadora-ventas?modulo=comercial"
hx-target="body"
hx-swap="beforeend"
hx-on::before-request="document.getElementById('modal-calculadora-ventas')?.remove()"
```
El `hx-on::before-request` evita duplicados si se abre dos veces sin cerrar.

### Logica de permisos (can_edit_constants)
`can_edit_constants = is_admin_or_manager AND can_edit`
- ADMIN → siempre True
- MANAGER + editor/admin de modulo → True
- MANAGER + viewer → False
- USER (cualquier rol modulo) → False

El parametro `?modulo=xxx` determina qué rol de módulo se evalúa.

### Formulas (cadena completa)
- `consumo_anual = consumo * 12`
- `conversion_kwp = consumo_anual / 1500`
- `precio_por_kilo = conversion_kwp * 600`
- `costo_sistema = precio_por_kilo * tc`  → mostrado en MXN + referencia USD
- `dias = consumo / 30.5`
- `horas_solares = dias / 5.5`
- `porcentaje_efectividad = horas_solares / 0.8`
- `capacidad_panel = porcentaje_efectividad / 0.71`  ← OJO: 0.71 no 0.071
- `numero_paneles = Math.floor(capacidad_panel)`

### TC (tipo de cambio)
- Se obtiene de `TipoCambioService.get_tasa_actual(conn)`
- Regla: `tc_efectivo = max(tc_valor, 20.0)` — minimo 20 si BD tiene valor menor
- Manager/editor puede sobreescribir el TC manualmente desde la seccion de constantes

### Constantes editables (solo manager/editor)
600, 1500, 30.5, 5.5, 0.8, 0.71, TC manual

### UI Mobile
- Bottom sheet (`items-end` en movil, `items-center sm:` en desktop)
- `max-h-[92dvh]` con `dvh` para ajuste dinamico cuando teclado virtual abre
- `inputmode="decimal"` en todos los inputs para teclado correcto en iOS
- Tarjetas de resultado en `grid-cols-2` en movil (lado a lado)
