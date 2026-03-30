# Roadmap: Correcciones y Mejoras KPIs Simulacion

**Creado:** 2026-02-09
**Estado Global:** TODAS LAS FASES COMPLETADAS (1-5)

---

## Fases Completadas (Resumen)

### FASE 1: Bug Fixes y Limpieza — COMPLETADA
- Codigo muerto, bare except, async sin await, comentarios dev

### FASE 2: Mitigacion Hardcoding — COMPLETADA
- Columna `es_no_viable` en `tb_cat_motivos_cierre`, parametrizacion SQL

### FASE 3: Conteo de Sitios — COMPLETADA
- 5 dataclasses + 3 queries SQL + 7 mapeos + 7 templates

### FASE 4: Refinamiento Score — COMPLETADA
- Techo removido (`min(1.0, ...)` eliminado), scores pueden superar 100

### FASE 5: Consolidacion Templates Legacy → Duales — COMPLETADA
- **5.1:** Eliminados 5 endpoints dead code en report_router.py (~155 lineas)
- **5.2:** tabs.html migrado de kpis_cards.html → kpis_cards_duales.html
- **5.3:** Eliminados 8 archivos (5 templates legacy + 3 duplicados)
  - Legacy: kpis_cards.html, tech_tables.html, semaforo_table.html, user_detail.html, monthly_pivot.html
  - Duplicados: simulacion/partials/resumen_ejecutivo.html, resumen_usuario.html, modals/explicacion_metricas.html
- **5.4:** Eliminadas ~14 properties legacy de dataclasses (MetricasGenerales, MetricaTecnologia, FilaContabilizacion, MetricaUsuario) + 2 keys legacy del resumen mensual
- **5.5:** Verificacion — grep confirma 0 referencias a templates/properties eliminados
  - Hallazgo extra: pdf_generator.py y report_router.py /api/metricas usaban properties legacy → migrados a nombres canonicos con sufijo `_compromiso`

**Archivos modificados en Fase 5:** report_router.py, report_service.py, pdf_generator.py, tabs.html
**Archivos eliminados en Fase 5:** 8 templates

---

## Pendiente: Verificacion Manual
- Ejecutar app y navegar a `/simulacion/reportes` (tabs.html)
- Navegar a analisis detallado (analisis_detallado_content.html)
- Generar PDF y verificar datos correctos
- Pendiente commit de todos los cambios

---

## Modelo de Datos KPI (aclarado 2026-03-13)

- **`tb_simulaciones_adicionales`** = variantes de UNA MISMA solicitud (análogo a multi-sitio). Ej: "simula 50kWp, 75kWp y 100kWp". Se insertan al cierre del padre. Cuentan en el mes del padre (correcto, son parte del mismo pedido).
- **Child opportunities (`parent_id`)** = actualizaciones secuenciales reales. Cada update comercial genera un nuevo registro en `tb_oportunidades` con `parent_id`. Tiene su propia `fecha_solicitud` y ciclo completo hasta ENTREGADO. Cuentan en su propio mes (correcto).
- **KPI mensual:** una oportunidad marcada ENTREGADO cuenta en el mes de su propia `fecha_solicitud`, no en el del padre.
- **Árbol `parent_id`:** profundidad máxima 6 niveles (verificado MCP 2026-03-13, 168 oportunidades totales). NO asumir que siempre apunta a la raíz — usar CTE recursiva para resolver raíz real.

---

## Feature Alta Iteración (implementado 2026-03-13)

- **Qué hace:** sección al final del PDF de reportes que muestra ciclos con más de 3 actualizaciones
- **Granularidad:** por ciclo (raíz del árbol parent_id), no por cliente — evita contar proyectos independientes del mismo cliente como un solo acumulado
- **Query:** `get_clientes_alta_iteracion()` en `db_service.py` — CTE recursiva + 3 CTEs adicionales
- **Columnas:** cliente, nombre del proyecto (raíz), badge actualizaciones, resumen del ciclo (N Pre Oferta · N Actualizacion · ...), solicitantes
- **Template:** `templates/pdf/simulacion/reporte_analitica.html` — sección condicional al final
- **Umbral:** parámetro configurable, default 3 (más de 3 = aparece en alerta)
- **Datos en `get_all_report_data()`:** clave `'alta_iteracion'`
