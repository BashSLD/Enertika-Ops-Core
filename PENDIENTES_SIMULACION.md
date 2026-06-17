# Pendientes — Módulo Simulación

**Última actualización:** 2026-06-17

---

## 0. Decouple FV/BESS — MERGEADO Y DESPLEGADO a `main` (2026-06-16)

**Estado (2026-06-17, verificado):** Decouple FV/BESS + Montaje de oferta + correcciones de reportes
**IMPLEMENTADOS, mergeados y desplegados**. `main` @ `099f573` incluye todo hasta `ffac007`
(fast-forward `e17244e..ffac007`). Migraciones **108–112 aplicadas en PROD y DEV**. El sync de
Fase 5 ya corre en producción — las entregas nuevas registran fila de componente.

**HECHO (ya no es pendiente):**
- Montaje de oferta + exclusión KPIs (mig 111). Detalle: `MD/PLAN_MONTAJE_OFERTA_KPIS_SIMULACION.md`.
- Decouple Fases 1 (mig 108), 3 (botón "FV Terminado"), 4 (reportes), 5 (sync, mig 110) — código,
  commiteado y desplegado.
- Correcciones UI/PDF (commiteadas). Detalle: `MD/CORRECCIONES_REPORTES_DECOUPLE_FV_BESS.md`.
- Sesión 2: tiempo de entrega medido desde el componente FV (`_TIEMPO_FV_HORAS`,
  `report_db_service.py`); tooltips en cards KPI y secciones; tabla "Desempeño por Tecnología"
  muestra "—" para BESS; fix de días negativos (`GREATEST(...,0)`) en `metrics_db_service.py`;
  drill-down por tecnología en "Tiempo de entrega"; separación de la sección BESS en el PDF.
  Commiteado en `cce7d83` / `399c8da` / `ffac007`.

**HECHO — Decouple Fase 2 (Excel), aplicada en PROD 2026-06-17:**
`scripts/decouple_fv_bess/importar_correccion.py --apply` corrido contra PROD (296 oportunidades)
con `correccion_fv_bess.xlsx` (45 filas revisadas por el equipo). Resultado: 40 componentes con
`fecha_entrega` FV actualizada, 37 magnitudes kWp y 33 magnitudes kWh corregidas. 11 filas omitidas
sin cambios (levantamientos, canceladas, no localizadas, "todo ok") — `validate()` se ajustó para
omitirlas (en vez de error) cuando tienen NOTAS que lo justifican. 16 reclasificaciones de tecnología
(`RECLASIFICAR_TECNOLOGIA`) quedaron **fuera de alcance a propósito** (decisión: "Solo Fase 2") — no
se tocó `id_tecnologia` ni se reclasificó ninguna oportunidad; quedan como seguimiento manual aparte
(Fase 2b, sin fecha). Verificación Paso 4 del runbook: invariante FV-family intacto (híbrido/BESS
puro sin cambios), 0 híbridos entregados sin fecha FV, magnitudes reconciliadas (BESS 66,332.52 kWh /
FV 59,291.81 kWp).

**PENDIENTE:**
1. **Decouple Fase 2b (reclasificación de tecnología)** — De las 16 filas con
   `RECLASIFICAR_TECNOLOGIA`, solo 6 OPs son cambios reales (las otras 10 son confirmaciones de
   "sigue igual"): OP-2605251110 (BESS→FV), OP-2603110722, OP-2605120529, OP-2605171727 (FV→FV+BESS),
   OP-2602170749 (FV+BESS→FV), OP-2602200751 (FV+BESS→BESS). **Decisión 2026-06-17: no se aplican
   por ahora** — se quedan como están. Mientras no se reclasifiquen, sus componentes con
   `magnitud=0` (ej. OP-2602200751) siguen contando en el KPI de tiempo de entrega del componente
   que ya no aplica (a tiempo/tarde), aunque no afecten el KPI de volumen. Retomar solo si el equipo
   pide cerrar esto formalmente.
2. ~~Decouple Fase 6 (recordatorio 16:00 MX)~~ — **CERRADO 2026-06-17, no procede.** Decisión del
   equipo: no se construye el recordatorio por correo (worker task + destinatarios en admin).
3. ~~Full-sync Fase 5~~ — **HECHO 2026-06-17**: corrido `sync_componentes_oportunidad` para
   OP-2605210946 y OP-2605221002 (los 2 KPI NULL históricos reales); ambos quedaron con
   `kpi_status` calculado. OP-2606150852 también salió en el barrido con KPI NULL pero es
   exclusión legítima (`excluir_kpis_simulacion=true`, pasó por Montaje/Monitoreo) — NULL correcto
   por diseño, no requiere acción.
4. ~~Bug `editado_manual` en Fase 2~~ — **CORREGIDO 2026-06-17**: `importar_correccion.py` (Fase 2)
   escribió fecha/magnitud en 83 filas de `tb_entregas_componente` sin marcar `editado_manual=true`,
   dejándolas expuestas a que un `sync_componentes_oportunidad` futuro las revirtiera
   silenciosamente. Fix aplicado en dos partes: (a) retroactivo — nuevo modo
   `--fix-editado-manual` del script, corrido contra PROD, marcó 74 componentes (verificado por
   query independiente); los 9 de diferencia con el "83" inicial eran filas tocadas hoy por otras
   razones, no por la corrección del Excel; (b) las tres `UPDATE` de `apply_row()` ahora marcan
   `editado_manual=true` para que una futura re-ejecución no repita el problema.

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

**Plan detallado:** `MD/PLAN_MONTAJE_OFERTA_KPIS_SIMULACION.md` (archivado, ejecutado).

**Estado (2026-06-16): IMPLEMENTADO COMPLETO (incl. reportes PDF).**

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

**`migrations/112_backfill_entregas_componente_historico.sql` YA APLICADA** en PROD y DEV
(backfill histórico completo de `tb_entregas_componente`; verificado 2026-06-16: 435 filas).
Lo único que falta es el **pipe + deploy** de la rama (ver sección 0).

---

## 6. Tiempo de entrega FV — negativos no clampados en reportes (nit, no urgente)

**Estado:** Detectado en code-review 2026-06-16. Impacto marginal; documentado, sin corregir.

**Contexto:** `_TIEMPO_FV_HORAS` en `modules/simulacion/report_db_service.py`
(`EXTRACT(EPOCH FROM (ec.fecha_entrega - o.fecha_solicitud)) / 3600.0`) **no** clampa a 0,
mientras que `modules/simulacion/metrics_db_service.py` sí usa `GREATEST(..., 0)` para el mismo
concepto. En PROD hay **4 componentes FV** con `fecha_entrega < fecha_solicitud` (error de captura),
lo que produce días negativos en el promedio de los reportes.

**Impacto medido (PROD, 2026-06-16):** el promedio FV cambia de **7.403 → 7.408 días** (5 milésimas;
peor negativo −0.7 días). Un tipo/tecnología con un único componente negativo podría mostrar días
negativos en la tabla.

**Fix (opcional, ~1 línea):** envolver la constante `_TIEMPO_FV_HORAS` en
`GREATEST(EXTRACT(...) / 3600.0, 0)` para alinearla con `metrics_db_service` (aplica a las ~6 queries
que la usan). Alternativa: corregir las 4 capturas de `fecha_entrega` en origen.

---

## 7. Reportes — `SUM(DISTINCT)` en totales de potencia/capacidad

**Estado:** Detectado en validación de la Fase 4 (2026-06-16). No bloqueante; probablemente
preexistente (el refactor de Fase 4 conservó el patrón, no lo introdujo). No afecta los KPIs de
entrega/cumplimiento.

**Contexto:** En `modules/simulacion/report_db_service.py`, los métodos `get_report_metricas_tech`
y `get_report_metricas_tech_batch` calculan los totales por tecnología así:

```sql
COALESCE(SUM(DISTINCT potencia_cierre_fv_kwp), 0) as potencia_total_kwp,
COALESCE(SUM(DISTINCT capacidad_cierre_bess_kwh), 0) as capacidad_total_kwh,
```

El `SUM(DISTINCT)` busca evitar inflar el total cuando una oportunidad multisitio repite el mismo
`o.potencia_cierre_fv_kwp` en cada fila del UNION (sitios + sim_adicionales). El problema es que
`DISTINCT` deduplica por **valor**, no por oportunidad: si dos oportunidades distintas de la misma
tecnología tienen exactamente el mismo kWp (o kWh), se suma una sola vez → el total queda
subestimado.

**Fix sugerido:** sumar potencia/capacidad una sola vez por oportunidad antes de agregar por
tecnología (CTE que tome `DISTINCT (id_oportunidad, potencia_cierre_fv_kwp)` y luego `SUM`), en lugar
de `SUM(DISTINCT valor)` sobre las filas explotadas por sitio.

**Esfuerzo estimado:** Bajo. Verificar antes si esos totales se consumen en algún tablero/PDF
sensible; si nadie los usa para decisiones, baja prioridad.
