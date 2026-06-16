# Pendientes — Módulo Simulación

**Última actualización:** 2026-06-16

---

## 1. Botón "Historial" en Métricas Operativas

**Estado:** Sin punto de entrada — el historial fue removido del modal de actualización y aún no se re-expone.

**Contexto:** El historial de transiciones (log de estatus, "Insertar evento faltante", "Reversión de cierre Admin") vivía en el modal de actualización. Se removió en commit `e0969a3` para simplificar ese modal pero nunca se creó la entrada alternativa en métricas.

**Plan acordado:**
1. `GET /simulacion/historial/{id_oportunidad}/modal` — nuevo endpoint, `require_manager_access`, reutiliza `_build_historial_context` existente.
2. `templates/simulacion/modals/historial_modal.html` — modal wrapper sobre el partial `historial_timeline.html` existente.
3. Botón "Historial" en cada fila de `detalle_oportunidades_estatus.html` y `detalle_oportunidades_transicion.html`, con `hx-target="#modal-action-container"`.

**Esfuerzo estimado:** Bajo — reutiliza código existente, solo falta el endpoint y el wrapper modal.

---

## 2. Cuello de Botella DG — Métrica en días calendario vs. días hábiles

**Estado:** Causa raíz identificada (2026-06-15). Pendiente confirmación del equipo sobre si el tiempo es aceptable; solución técnica vinculada al ítem 3.

**Contexto:** Análisis de BD (prod) muestra que las 3 OPs con mayor tiempo en "En Revisión" son:

| OP | Cliente / Proyecto | Entrada | Salida | Días calendario | Días hábiles reales |
|---|---|---|---|---|---|
| OP-2603111305 | HORTÍCOLA CIMARRÓN | 12-Mar | 23-Mar | 11.3 | ~7 |
| OP-2603131305 | BESS Aparceros Unidos | 20-Mar | 31-Mar | 11.3 | ~7 |
| OP-2603230935 | DANZANTE BAY — Loreto BCS | 27-Mar | 07-Abr | 11.1 | ~7 |

Las fechas **no están mal capturadas** (`fecha_cambio_real` coincide con la fecha de registro en los 3 casos). El "inflado" viene de que `get_metricas_ciclo_revision` calcula el intervalo como días calendario (`EXTRACT(EPOCH FROM (fin - inicio)) / 86400`), y cada OP abarca 2 fines de semana (4 días no hábiles). Los `fecha_cambio_sla` se normalizan a las 17:30 del día hábil correspondiente (via `SLACalculator.calculate_deadline`), pero eso solo ajusta el punto de inicio/fin — no descuenta los fines de semana intermedios.

**Causa raíz técnica:** `get_metricas_ciclo_revision` necesita calcular días hábiles entre dos `fecha_cambio_sla`, no días calendario. Eso requiere la misma función que el ítem 3 (`fn_segundos_habiles_mx`).

**Pendiente:**
- Confirmar con el equipo si **7 días hábiles** en revisión es un tiempo aceptable o sigue siendo un cuello de botella real (ver `ENCUESTA_PENDIENTES_SIMULACION.md` Bloque 1).
- Una vez corregido `fn_segundos_habiles_mx` (ítem 3), reemplazar el cálculo de intervalo en `get_metricas_ciclo_revision` por días hábiles.
- No se requiere UPDATE retroactivo en `tb_historial_estatus` — los datos están correctos; el problema es el cálculo.

**Bloqueante:** Depende de la corrección del ítem 3 en lo técnico, y de la respuesta del equipo en lo de negocio.

---

## 3. PDF KPI — Sección "Espera de Dirección" (Desactivada)

**Estado:** Desactivada intencionalmente. Bloqueada por bug en función SQL.

**Contexto:** La sección "Espera de Dirección" del PDF de KPIs fue desactivada en commit `8ac9701` porque `fn_segundos_habiles_mx` (migración 107) no respeta la jornada laboral ni la hora de corte, produciendo valores incorrectos.

**Para desbloquear:**
- Corregir `fn_segundos_habiles_mx` para que descuente horas fuera de jornada (configurable vía `tb_configuracion_global`).
- Reactivar la sección en `modules/simulacion/report_service.py`.
- Verificar que los segundos hábiles calculados coincidan con expectativas manuales.

**Impacto adicional:** corregir esta función también desbloquea el ítem 2 — permite que `get_metricas_ciclo_revision` muestre días hábiles reales en lugar de días calendario.

**Archivo donde está desactivado:** `modules/simulacion/report_service.py` — buscar comentario sobre "Espera de Direccion".

---

## 4. PDF Analítico — Ítems pendientes de definición de negocio

> Fases A, B y C del plan original ya implementadas. Los siguientes ítems requieren
> decisión antes de implementarse.

### 4a. KPI de tasa de conversión / win-rate

Agregar tarjeta KPI con el porcentaje de oportunidades que cierran como "Ganada".

**Bloqueante:** Acordar el denominador (¿total del periodo? ¿solo las que entregaron oferta? ¿solo las cerradas?).

**Archivo:** `templates/pdf/simulacion/reporte_analitica.html` — sección kpi-grid.
**Dato disponible:** `m.ganadas` ya existe; falta el denominador acordado.

### 4b. Nota de reconciliación de totales entre secciones

Las secciones del PDF muestran conteos distintos (ej. 56 / 81 / 84) porque cada una aplica filtros diferentes. Agregar nota al pie que explique el criterio de cada sección.

**Bloqueante:** Definir el texto oficial y qué filtros aplica cada sección.

**Archivo:** `templates/pdf/simulacion/reporte_analitica.html`

### 4c. Narrativa ejecutiva + comparación vs. periodo anterior (deltas)

Párrafo automático al inicio: "En el periodo analizado se recibieron X solicitudes (+12% vs. periodo anterior)..."

**Bloqueante:** Requiere doble fetch (periodo actual + anterior) y definir cómo calcular el "periodo anterior" con rangos irregulares.

**Archivos:** `modules/simulacion/report_service.py` (nuevo `get_datos_periodo_anterior()`), `report_router.py`, `reporte_analitica.html`.

### 4d. Mostrar nombres en filtros en vez de IDs

La portada muestra el ID de tecnología y el ID de responsable cuando se filtra. Debe mostrar el nombre legible.

**Bloqueante:** Requiere lookups a `tb_cat_tecnologias` y `tb_usuarios` al generar el PDF.

**Archivo:** `modules/simulacion/report_router.py` — enriquecer `filtros_ctx`. Impacto ~10 líneas.

---

## 5. Estatus "Montaje de oferta" y exclusión KPI de Monitoreo/Montaje

**Plan detallado:** `PLAN_MONTAJE_OFERTA_KPIS_SIMULACION.md`

**Estado (2026-06-16): IMPLEMENTADO salvo reportes PDF.**

Se agregó el estatus `Montaje de oferta` (similar a `Monitoreo de Cotización`). Ambos son
estatus especiales: pueden saltar el flujo normal de revisión, pueden pasar después a
`Entregado`, no cuentan en KPIs ni métricas operativas, y se contabilizan por separado desde
historial. La exclusión se identifica por el flag de catálogo
`tb_cat_estatus_oportunidades.activa_exclusion_kpis_simulacion` (no por nombre) y se persiste en
`tb_oportunidades.excluir_kpis_simulacion` de forma monótona (una vez true, se conserva).

- Migración **111** aplicada y verificada en PROD (Montaje = id 16, orden 7; backfill por historial).
- Implementado en `service.py`, `db_service.py`, `metrics_db_service.py`, modal y `metricas_datos.html`.
- Tests en `tests/test_simulacion_status_notifications.py` y `tests/test_simulacion_metrics_service.py`.

**Fase 4 del decouple FV/BESS — CÓDIGO LISTO 2026-06-16.** Reescritura única de
`modules/simulacion/report_db_service.py`: los KPIs de entrega/cumplimiento leen de
`tb_entregas_componente` (`componente='FV'`) con JOIN a `tb_oportunidades` + filtro
`COALESCE(o.excluir_kpis_simulacion, false) = false` + `e.cuenta_para_kpi=true` (reemplaza el
hardcode `IN(entregado,perdido,ganada)`). Sección BESS aparte (`SeccionBESS` + render en
`reporte_analitica.html`). Conteos de volumen sin cambios. Builder `_P` elimina el frágil
`len(params)-N`.

**FALTA antes de desplegar:** aplicar `migrations/112_backfill_entregas_componente_historico.sql`
en PROD (backfill histórico completo de `tb_entregas_componente` sin filtro de año; sin él, los
reportes que abarquen 2025 perderían los sitios FV/BESS puros que la mig 108 dejó fuera).
