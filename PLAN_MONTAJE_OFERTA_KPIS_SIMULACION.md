# Plan: Montaje de oferta y exclusion de KPIs en Simulacion

> **Afinado y verificado contra código el 2026-06-15.** Ver secciones
> "Estado verificado" e "Integración con decouple FV/BESS" al final.
>
> **Estado (2026-06-16): IMPLEMENTADO salvo reportes PDF (Fase 4 decouple).**
> - Migración **111** aplicada y verificada en PROD (columnas + estatus Montaje id 16 + backfill).
> - `service.py`: clave `montaje_oferta` en `_get_status_ids`; `_validate_status_transition` y
>   `_validate_status_pair` generalizados por el flag `activa_exclusion_kpis_simulacion`
>   (ya no hardcodean "Monitoreo de Cotización"); marca `excluir_kpis_simulacion` monótono (OR).
> - `db_service.py`: `update_oportunidad_padre` setea el flag monótono; guards en
>   `recalcular_kpis_sitios_por_deadline` y `sync_componentes_oportunidad` (helper
>   `_oportunidad_excluida`) → KPI NULL cuando excluida, conservando fecha/estatus.
> - `metrics_db_service.py`: filtro de exclusión en los 7 métodos vía `_build_filters`
>   (`excluir_kpis=True` default); `get_tiempo_en_monitoreo` reconvertido a
>   `get_conteo_casos_especiales` (conteo informativo Monitoreo+Montaje desde historial).
> - UI: modal `update_oportunidades.html` (flag `montaje_oferta_id`, validez por flag, panel
>   stand-by, doble confirmación `confirm()` en `validateForm`) y `metricas_datos.html`
>   (tarjetas de conteo "Casos especiales").
> - Tests: `tests/test_simulacion_status_notifications.py` (transiciones) y
>   `tests/test_simulacion_metrics_service.py` (exclusión + conteo).
> - **PENDIENTE:** `report_db_service.py` (KPIs del PDF) → se integra en la **Fase 4 del decouple**.

## Objetivo

Agregar el nuevo estatus `Montaje de oferta` al modulo de Simulacion y ajustar el tratamiento de `Monitoreo de Cotización` para que ambos funcionen como estatus especiales:

- Se pueden seleccionar sin pasar por el flujo normal `En Revisión` -> `Entregado`.
- Despues pueden pasar a `Entregado`.
- No cuentan en KPIs.
- No cuentan en metricas operativas.
- Si deben contabilizarse por separado como volumen de casos especiales.

## Acuerdos definidos

1. No conviene reutilizar directamente `cuenta_para_kpi` como bandera principal de exclusion de oportunidades.
2. Se agregara una nueva columna en oportunidades: `excluir_kpis_simulacion`.
3. La exclusion tambien aplica a metricas operativas, no solo a KPIs del reporte.
4. La exclusion se activa al cambiar la oportunidad a `Monitoreo de Cotización` o `Montaje de oferta`.
5. La exclusion debe conservarse aunque despues la oportunidad pase a `Entregado`.
6. La contabilizacion de Monitoreo/Montaje debe hacerse desde historial de estatus, no solo desde el estatus actual, porque despues pueden quedar como `Entregado`.
7. Debe existir doble confirmacion en UI solo al seleccionar `Monitoreo de Cotización` o `Montaje de oferta`.

## Veredicto sobre `cuenta_para_kpi`

`cuenta_para_kpi` existe en `tb_cat_estatus_oportunidades`, pero actualmente no se usa en el codigo; solo aparece en migraciones y seeds.

No debe usarse como reemplazo global porque mezcla conceptos distintos:

- `total_solicitudes` debe incluir estados activos aunque `cuenta_para_kpi=false`.
- `Cancelado` tiene `cuenta_para_kpi=false`, pero aun debe contarse como salida operativa o comercial segun la metrica.
- `Ganada`, `Perdido` y `Entregado` necesitan lecturas de negocio especificas.
- Algunas graficas son distribuciones de volumen, no KPIs.

Si conviene un refactor parcial y controlado:

- Usar `cuenta_para_kpi=true` solo para metricas de entrega/cumplimiento.
- Combinarlo con `o.excluir_kpis_simulacion=false`.
- Mantener condiciones explicitas por estatus para solicitudes, canceladas, no viables, ganadas, espera y distribuciones.

## Estado verificado contra código (2026-06-15)

Hechos confirmados (MCP PROD + lectura de código), que refinan el plan:

- **Columnas no existen aún:** `tb_oportunidades.excluir_kpis_simulacion` ni
  `tb_cat_estatus_oportunidades.activa_exclusion_kpis_simulacion`.
- **Estatus "Montaje de oferta" no existe.** Catálogo SIMULACION actual (orden):
  Pendiente 1, En Proceso 2, En Revisión 3, Comentarios Recibidos 4, Entregado 5,
  Monitoreo de Cotización 6 (id 14), Ganada 7 (id 7), Cancelado 8 (id 5), Perdido 9 (id 6).
- **Numeración de migración:** la próxima libre es **111** (108/109/110 usadas esta sesión;
  recalcular con `Glob migrations/*.sql`, no asumir).
- **`cuenta_para_kpi` ya poblado pero NO usado en código:** Entregado=true, Ganada=true,
  Perdido=true; el resto false. Hoy los reportes usan `IN (entregado,perdido,ganada)` hardcoded.

Refinamientos concretos que el plan original no especificaba:

1. **`service._get_status_ids()` (service.py:101-109)** devuelve un dict fijo de IDs. Hay que
   **añadir la clave `montaje_oferta`** ahí; de lo contrario el modal y la validación no la verán.
2. **`_validate_status_transition()` (service.py:1041)** trata Monitoreo **hardcodeando el nombre**
   (`actual['nombre'] == 'Monitoreo de Cotización' ...`). En vez de añadir otro nombre hardcodeado,
   **generalizar por el flag** `activa_exclusion_kpis_simulacion` del catálogo: "si origen o destino
   es un estatus especial (flag=true), permitir entrada/salida a activos y paso a Entregado".
   Esto cubre Monitoreo y Montaje sin más cambios futuros.
3. **Modal (`update_oportunidades.html`)**: los IDs se exponen como `status_ids.X` en el `x-data`
   (líneas 10-14). Añadir `montaje_oferta_id: {{ status_ids.montaje_oferta | default('null') }}`.
   El panel especial de Monitoreo está en `x-show="status === monitoreo_cotizacion_id"` (línea 280)
   y la validez de transición en Jinja (líneas 261-266) — extender ambos para Montaje. La doble
   confirmación: **reusar el patrón `hx-confirm`** ya usado por el botón "FV Terminado" (sesión
   decouple), por consistencia, en vez de introducir lógica Alpine nueva.
4. **`metrics_db_service.py`** tiene 11 métodos. Aplicar exclusión en: `get_tiempo_por_estatus`,
   `get_analisis_ciclos`, `get_metricas_ciclo_revision`, `get_comparativo_sla_ajustado`,
   `get_tiempo_entrega_por_tecnologia`, `get_detalle_entrega`, `get_calidad_registro`.
   **`get_tiempo_en_monitoreo` (línea 649)** es el que se reconvierte a conteo informativo
   (Monitoreo + Montaje), desde historial.

## Cambio de datos propuesto

Crear una migracion idempotente para:

1. Agregar columna al catalogo:

```sql
ALTER TABLE tb_cat_estatus_oportunidades
ADD COLUMN IF NOT EXISTS activa_exclusion_kpis_simulacion boolean NOT NULL DEFAULT false;
```

2. Agregar columna a oportunidades:

```sql
ALTER TABLE tb_oportunidades
ADD COLUMN IF NOT EXISTS excluir_kpis_simulacion boolean NOT NULL DEFAULT false;
```

3. Crear o actualizar estatus `Montaje de oferta`:

- `modulo_aplicable = 'SIMULACION'`
- `cuenta_para_kpi = false`
- `es_estatus_final = false`
- `activa_exclusion_kpis_simulacion = true`

4. Actualizar `Monitoreo de Cotización`:

- `cuenta_para_kpi = false`
- `es_estatus_final = false`
- `activa_exclusion_kpis_simulacion = true`

5. Orden sugerido de catalogo:

- `Pendiente`: 1
- `En Proceso`: 2
- `En Revisión`: 3
- `Comentarios Recibidos`: 4
- `Entregado`: 5
- `Monitoreo de Cotización`: 6
- `Montaje de oferta`: 7
- `Ganada`: 8
- `Cancelado`: 9
- `Perdido`: 10

6. Backfill:

Marcar `tb_oportunidades.excluir_kpis_simulacion=true` para toda oportunidad que tenga historial en `Monitoreo de Cotización` o `Montaje de oferta`.

## Flujo de estatus

Actualizar la validacion de transiciones para tratar como estatus especiales:

- `Monitoreo de Cotización`
- `Montaje de oferta`

Reglas:

- Se permite entrar a cualquiera de esos estatus desde estados activos.
- Se permite salir de esos estatus hacia estados activos permitidos.
- Se permite pasar de esos estatus a `Entregado`.
- `Entregado` debe permitirse desde:
  - `Comentarios Recibidos`
  - `Monitoreo de Cotización`
  - `Montaje de oferta`

Al cambiar hacia un estatus con `activa_exclusion_kpis_simulacion=true`, la oportunidad debe quedar con `excluir_kpis_simulacion=true`.

## UI

Actualizar `templates/simulacion/modals/update_oportunidades.html`:

- Agregar identificador Alpine para `montaje_oferta_id`.
- Aplicar la misma logica especial que hoy tiene `Monitoreo de Cotización`.
- Permitir `Entregado` desde `Montaje de oferta`.
- Agregar confirmacion extra solo para:
  - `Monitoreo de Cotización`
  - `Montaje de oferta`

Texto sugerido:

```text
Estas seguro de marcar como "{status}"?
Esta oportunidad se contabilizara aparte y no contara en KPIs ni en metricas operativas.
```

## KPIs y reportes

> **DECISIÓN DE SECUENCIACIÓN (2026-06-15):** Montaje **NO** toca `report_db_service.py` en su
> propia entrega. Ese archivo (CTEs frágiles) se reescribe **una sola vez** en la **Fase 4 del
> decouple**, integrando a la vez: lectura de componentes + separación BESS + filtro
> `excluir_kpis_simulacion` + `cuenta_para_kpi`. Montaje sí aplica la exclusión en
> `metrics_db_service.py` (métricas operativas), que es independiente. Costo temporal aceptado:
> entre el deploy de Montaje y la Fase 4, el PDF de KPIs aún contaría las oportunidades de Montaje.

Cuando se haga la Fase 4, actualizar consultas en `modules/simulacion/report_db_service.py` para excluir:

```sql
COALESCE(o.excluir_kpis_simulacion, false) = false
```

Aplicar la exclusion en:

- Cumplimiento SLA interno.
- Cumplimiento compromiso cliente.
- Tiempo promedio de entrega.
- Entregas a tiempo/tarde.
- Pendientes de fecha de entrega usadas en KPI.
- Tablas de contabilizacion KPI.
- Resumen mensual KPI.
- Score o indicadores derivados de cumplimiento.

Refactor parcial recomendado:

- Donde el concepto sea entrega/cumplimiento, usar `e.cuenta_para_kpi=true`.
- Donde el concepto sea una categoria de negocio, conservar filtro por estatus especifico.

No cambiar a `cuenta_para_kpi` en:

- `total_solicitudes`
- `en_espera`
- `canceladas`
- `no_viables`
- `ganadas`
- distribuciones por tecnologia, vendedor, cliente o estatus
- conteos historicos que no son KPI

## Metricas operativas

Actualizar `modules/simulacion/metrics_db_service.py` para excluir oportunidades con:

```sql
COALESCE(o.excluir_kpis_simulacion, false) = false
```

Aplicar en:

- Tiempo por estatus.
- Ciclo de revision.
- Comparativo SLA ajustado.
- Tiempo de entrega por tecnologia.
- Detalle de entrega.
- Transiciones actuales del pipeline.
- Metricas de calidad si se interpretan como parte de metricas operativas.

La seccion actual de `Tiempo en Monitoreo de Cotización` debe cambiarse a una seccion de conteo informativo:

- Total de oportunidades que pasaron por `Monitoreo de Cotización`.
- Total de oportunidades que pasaron por `Montaje de oferta`.
- Opcional: conteo actual abierto por cada estatus.

## Componentes y recalculos

Revisar estos puntos para evitar que una oportunidad excluida vuelva a generar KPIs:

- `sync_componentes_oportunidad`
- `recalcular_kpis_sitios_por_deadline`
- calculo de KPIs al marcar oportunidad como `Entregado`
- cascada de estatus/fecha hacia sitios y componentes

Decision recomendada:

- Mantener la actualizacion de estatus/fecha cuando aplique.
- No calcular KPI ni tiempos KPI para oportunidades con `excluir_kpis_simulacion=true`.
- Guardar valores KPI como `NULL` o no insertar registros KPI derivados para esas oportunidades, segun el patron actual de levantamientos.

## Contabilizacion separada

Usar historial de estatus como fuente:

```sql
tb_historial_estatus -> tb_cat_estatus_oportunidades
```

Esto permite contar correctamente aunque la oportunidad haya terminado en `Entregado`.

Conteos minimos:

- `monitoreo_cotizacion_total`
- `montaje_oferta_total`

Conteos opcionales:

- abiertos actualmente en Monitoreo
- abiertos actualmente en Montaje
- entregados despues de Monitoreo
- entregados despues de Montaje

## Pruebas sugeridas

Agregar o actualizar pruebas para:

- `Pendiente` -> `Montaje de oferta` permitido.
- `Montaje de oferta` -> `Entregado` permitido.
- `Monitoreo de Cotización` -> `Entregado` se conserva.
- Al entrar a Monitoreo/Montaje se marca `excluir_kpis_simulacion=true`.
- Una oportunidad excluida y entregada no entra en KPIs.
- Una oportunidad excluida no entra en metricas operativas.
- El backfill marca oportunidades con historial de Monitoreo.
- Los conteos separados usan historial y no solo estatus actual.

Archivos de prueba candidatos:

- `tests/test_simulacion_status_notifications.py`
- `tests/test_simulacion_metrics_service.py`

## Archivos principales a tocar en implementacion

- `migrations/`
- `modules/simulacion/service.py`
- `modules/simulacion/db_service.py`
- `modules/simulacion/report_db_service.py`
- `modules/simulacion/metrics_db_service.py`
- `templates/simulacion/modals/update_oportunidades.html`
- `templates/simulacion/partials/metricas_datos.html`
- pruebas relacionadas en `tests/`

## Puntero para `PENDIENTES_SIMULACION.md`

Agregar un item nuevo que apunte a este documento:

```markdown
## 5. Estatus "Montaje de oferta" y exclusion KPI de Monitoreo/Montaje

Plan detallado: `PLAN_MONTAJE_OFERTA_KPIS_SIMULACION.md`

Agregar estatus `Montaje de oferta`, similar a `Monitoreo de Cotización`.
Ambos pueden saltar el flujo normal de revision, pueden pasar despues a
`Entregado`, no cuentan en KPIs ni metricas operativas y se contabilizan
por separado.
```

## Riesgos y puntos a validar antes de implementar

1. Definir si los registros KPI existentes de oportunidades con historial de Monitoreo deben limpiarse o solo excluirse en consultas.
2. Confirmar si sitios/componentes de una oportunidad excluida deben quedar entregados sin KPI o no deben generar registros derivados.
3. Confirmar si las metricas de calidad tambien se consideran metricas operativas para esta exclusion.
4. Confirmar si se requiere una pestana nueva para `Montaje de oferta` o solo conteo dentro de dashboard/metricas.

---

## Integración con decouple FV/BESS (sesión 2026-06-15)

En esta sesión se implementó el **decouple FV/BESS** (ver `PLAN_DECOUPLE_FV_BESS.md`), que
introdujo la tabla **`tb_entregas_componente`** (KPIs a nivel componente FV/BESS). Este plan de
Montaje fue escrito ANTES y razona a nivel **oportunidad**, así que debe integrarse para no chocar.

### Colisión crítica: `report_db_service.py`
- **Fase 4 del decouple (pendiente):** reescribir los CTEs de KPI para leer de
  `tb_entregas_componente` + separar la sección BESS.
- **Este plan (Montaje):** añadir `COALESCE(o.excluir_kpis_simulacion,false)=false` + migrar a
  `cuenta_para_kpi` en las mismas queries.
- **Riesgo:** hacerlos por separado = doble refactor del mismo archivo, uno pisa al otro.
- **Decisión:** **hacer Montaje ANTES de la Fase 4**, o **fusionar ambos en un solo refactor** de
  `report_db_service.py`. NO hacer Fase 4 primero.

### El filtro de exclusión debe propagarse a componentes
- La exclusión es a nivel oportunidad (`o.excluir_kpis_simulacion`), pero las queries de KPI de la
  Fase 4 leen `tb_entregas_componente`. Por tanto esas queries deben **JOIN a `tb_oportunidades`**
  y filtrar `excluir_kpis_simulacion=false` (la tabla de componentes no replica ese flag).

### Guards en código del decouple ya commiteado
- **`sync_componentes_oportunidad` (db_service):** hoy calcula KPI para toda oportunidad. Debe
  **no calcular KPI** (dejar `kpi_status_* = NULL`) cuando `excluir_kpis_simulacion=true`, pero
  **sí** mantener fecha/estatus. Es el punto del plan "Componentes y recalculos" aplicado al sync.
- **`recalcular_kpis_sitios_por_deadline` (db_service):** mismo guard.
- **Botón "FV Terminado" (Fase 3):** marca KPI FV. Para un híbrido en Monitoreo/Montaje, ese KPI
  tampoco debería contar — el guard de exclusión en las queries de reporte lo cubre, pero validar
  que no se muestre como cumplimiento.

### Modal — unificar doble confirmación
- El botón "FV Terminado" ya usa `hx-confirm` (doble confirmación nativa). Reusar ese patrón para
  Monitoreo/Montaje en vez de lógica Alpine, para tener un solo mecanismo en el modal.

### Migraciones — orden
- Decouple: 108/109/110 (aplicadas). Montaje: **111** (recalcular con Glob).

## Secuenciación recomendada y nueva sesión

**Orden sugerido global:**
1. (Hecho) Decouple Fases 1, 3, 5 + saneamiento — commiteado en `feat/decouple-fv-bess`.
2. (Espera Excel) Decouple Fase 2 — import.
3. **Montaje (este plan)** — incluye los guards de exclusión en `sync`/`recalcular`.
4. **Decouple Fase 4 + Montaje en reportes** — un solo refactor de `report_db_service.py` que
   integre: lectura de componentes, separación BESS y filtro `excluir_kpis_simulacion`/`cuenta_para_kpi`.
5. Decouple Fase 6 — recordatorio 16:00 (independiente, puede ir en cualquier momento).

**Nueva sesión: SÍ recomendada para implementar Montaje.** Razones:
- El contexto de esta sesión ya está cargado con el decouple (~38%); Montaje es un cambio grande
  (migración + service + db_service + report_db_service + metrics_db_service + modal + tests).
- Conviene arrancar limpio con **este plan afinado** como entrada y `PLAN_DECOUPLE_FV_BESS.md` como
  referencia de la colisión.
- Antes de la nueva sesión: idealmente desplegar/mergear el código del decouple ya commiteado, para
  que Montaje parta de un `report_db_service.py` estable.

