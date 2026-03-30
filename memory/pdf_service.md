# core/pdf_service — Referencia

## Estado: Implementado y funcional (2026-02-25)

## Infraestructura
- **Motor:** WeasyPrint async via `run_in_executor`
- **CRÍTICO:** `pydyf>=0.6.0,<0.10.0` DEBE estar pineado en requirements.txt (pydyf 0.10+ cambia API de PDF.__init__ → TypeError)
- **FileSystemLoader root:** `templates/pdf/` — los templates usan `{% extends "_base.html" %}` (NO `"pdf/_base.html"` — eso buscaría `templates/pdf/pdf/_base.html` que no existe)
- **Infraestructura deploy:** `nixpacks.toml` (libpango, cairo…), `Dockerfile.dev`, `docker-compose.dev.yml`, `requirements.txt` (+weasyprint, pydyf<0.10.0, Pillow)

## Archivos
- `core/pdf_service/` — `service.py`, `image_processor.py`, `schemas.py`, `router.py`
- `templates/pdf/_base.html`, `visita_obra.html`, `simulacion/reporte_analitica.html`

## Endpoints
- **Visita obra:** `POST /pdf/visita-obra/generar` (multipart/form-data)
- **Simulacion:** `POST /simulacion/reportes/pdf/generar` — acepta `filtros_json` + `charts_json` (Form); charts = data URIs base64 desde Chart.js canvas del cliente

## Visita a Obra
- **Singleton:** `get_pdf_service()` retorna instancia global de `PDFService`
- **VisitaObraData:** Pydantic v2, validators HH:MM + fecha automática America/Mexico_City
- **Proyectos UI:** botón en `templates/proyectos/partials/content.html` → modal `visita_obra_modal.html`, endpoint `GET /proyectos/partials/visita-obra-modal`

## Simulacion PDF
- **Botón PDF en:** `templates/simulacion/reportes/analisis_detallado_inner.html` (captura charts); tabs.html también tiene botón pero SIN charts
- **Charts cliente-side:** canvases ocultos en `analisis_detallado_content.html`, `initPdfCharts()` global, `window._pdfCharts` dict, Chart.js `toBase64Image()`
- **Claves charts PDF template:** `estatus`, `mensual`, `tecnologia`, `kpi`, `motivos`

## Template reporte_analitica.html (rediseñado 2026-02-25)
- **Standalone** (NO extiende _base.html) — control total del layout
- **`@page :first { margin: 0 }`** → portada full-bleed; `@bottom-left/right` con CSS puro para footer páginas 2+
- **Portada:** gradiente navy, círculos decorativos absolutos, teal accent line, cover-bar inferior
- **WeasyPrint layout:** siempre `<table>` para columnas, NUNCA flexbox/grid
- **Páginas de contenido:**
  - Pág 2: KPIs (4 cards `border-collapse:separate`) + métricas secundarias + charts estatus+mensual
  - Pág 3: Tabla contabilización (`tablas.contabilizacion` — `FilaContabilizacion`) + tabla tendencia mensual (`tablas.mensual` — `Dict[str,FilaMensual]`)
  - Pág 4: Tabla tecnología + chart tecnología + charts kpi+motivos usuarios
  - Pág 5: Tabla resumen por usuario (semáforo verde/ámbar/rojo ≥80/≥60/<60)

## Schemas de datos clave
**FilaContabilizacion attrs:** `nombre`, `total`, `entregas_a_tiempo_interno`, `entregas_tarde_interno`, `porcentaje_a_tiempo_interno`, `semaforo_interno` ('green'/'amber'/'red'/'gray'), `es_levantamiento`, `sin_fecha`, `entregas_a_tiempo_compromiso`, `porcentaje_a_tiempo_compromiso`, `semaforo_compromiso`

**FilaMensual attrs:** `metrica` (str), `valores` (Dict[int,Any] — keys 1-12), `total`; claves del dict: `solicitudes_recibidas`, `ofertas_generadas`, `porcentaje_en_plazo_interno`, `en_espera`, `canceladas`, `perdidas`, etc.

**Jinja2 gotcha:** `clave in tablas.mensual` para verificar existencia; `tablas.mensual.get(clave)` para acceso seguro; NO usar `is defined` en valores de dict
