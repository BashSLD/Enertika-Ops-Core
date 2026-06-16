# Plan — Decouple FV / BESS en métricas de Simulación

**Creado:** 2026-06-15
**Estado:**
- **Fase 1 (schema + backfill) APLICADA y VERIFICADA en PROD el 2026-06-15.** 361 componentes
  (FV 306 / BESS 55); INVARIANTE FV-family intacta (378/230/108/184/154); magnitudes reconciliadas.
- **Saneamiento de ceros (`migrations/109`) APLICADO en PROD el 2026-06-15.** 23 ceros sin sentido
  → NULL (20 FV con kWh=0, 3 BESS con kWp=0). Backup: `scripts/decouple_fv_bess/_backup_saneamiento_109.json`.
  El universo del Excel bajó de 68 a **45 filas** (39 híbridos + 4 FV con kWh real + 2 BESS con kWp real).
- **Fase 2 (import del Excel):** script `scripts/decouple_fv_bess/importar_correccion.py` listo;
  espera a que el equipo llene el Excel (45 filas).
- **Fase 5 (sincronía) CÓDIGO LISTO 2026-06-15** — `migrations/110` APLICADA; falta desplegar código.
  `sync_componentes_oportunidad` + wiring en service (cierre padre y batch). Validado read-only:
  351/353 KPIs coinciden con backfill; 2 son mejoras (rellenan KPI NULL donde hay fecha).
- **Fase 3 (botón "FV Terminado") CÓDIGO LISTO 2026-06-15** — falta desplegar. db_service + service +
  endpoint `POST /simulacion/fv-terminado/{id}` + banner en modal (solo híbridos, doble confirmación).
- **Fase 4 (reportes + UI + PDF) CÓDIGO LISTO 2026-06-16** — reescritura única de
  `report_db_service.py`: KPIs de entrega leen de `tb_entregas_componente` (`componente='FV'`)
  con JOIN a oportunidades + `COALESCE(o.excluir_kpis_simulacion,false)=false` + `e.cuenta_para_kpi`
  (reemplaza el hardcode `IN(entregado,perdido,ganada)`); builder de params `_P` (mata `len(params)-N`);
  sección BESS separada (`get_report_seccion_bess` + dataclass `SeccionBESS` + render en
  `reporte_analitica.html`). Conteos de volumen (total_solicitudes, en_espera, canceladas,
  no_viables, ganadas, distribuciones) sin cambios. **Requiere `migrations/112`** (backfill histórico
  total de `tb_entregas_componente`, sin filtro de año) APLICADA en PROD para no perder KPIs de 2025.
  Validado read-only vs PROD: FV-family coincide (Δ≤1 por la "mejora" ya documentada en Fase 5).
- Refresh PROD→DEV sigue diferido (pruebas activas en DEV).
**Objetivo:** Separar las métricas de FV (responsabilidad de Simulación) de las de BESS
(responsabilidad de otra área) en oportunidades híbridas FV+BESS, sin alterar los KPIs
históricos de FV puro.

---

## 0. ADVERTENCIA CRÍTICA — Dos bases de datos distintas

Durante el análisis se detectó **split-brain entre dos proyectos Supabase**:

| | App `.env` | MCP Supabase |
|---|---|---|
| Rol | **DEV** (pruebas activas) | **PRODUCCIÓN** |
| Endpoint | `aws-1-us-east-2.pooler...` (`…1f16:1cd0…`) | otro servidor (`…1f13:838…`) |
| Total oportunidades | 286 | **293** |
| FV con kWh | 22 | **24** |

- **PRODUCCIÓN = la del MCP Supabase.** Toda corrección, migración y backfill se aplica ahí.
- `.env` apunta a DEV. Plan del usuario: refrescar DEV desde una copia de PROD **más adelante**
  (no ahora, por pruebas activas).
- **Implicación para herramientas:** el generador del Excel lee `.env` por defecto = DEV.
  Por eso el Excel se generó desde un snapshot JSON capturado de PROD vía MCP
  (`_data_prod.json`), NO desde `.env`. Ver sección 6.
- Antes de CUALQUIER ejecución, reconfirmar contra qué BD se está corriendo
  (`SELECT inet_server_addr(), count(*) FROM tb_oportunidades;` debe dar 293+ en PROD).

---

## 1. Snapshot baseline (PRODUCCIÓN, capturado 2026-06-15)

> Re-ejecutar estas consultas **después** del refactor y comparar. Lo marcado como
> "INVARIANTE" no debe cambiar; lo marcado como "esperado a cambiar" sí.

### A) Agregados por tecnología

| id | tecnología | ops | entregadas | con_kwp | con_kwh | sum_kwp | sum_kwh |
|----|-----------|-----|-----------|---------|---------|---------|---------|
| 1 | FV | 235 | 209 | 96 | 24 | 37 845.30 | 79 373.50 |
| 2 | BESS | 18 | 14 | 5 | 8 | 335.40 | 20 158.60 |
| 3 | FV + BESS | 39 | 35 | 17 | 17 | 8 362.84 | 24 811.32 |
| 5 | BOMBEO SOLAR | 1 | 1 | 1 | 0 | 16.20 | 0.00 |

```sql
SELECT t.id AS id_tec, t.nombre AS tecnologia,
  COUNT(*) AS ops,
  COUNT(*) FILTER (WHERE o.fecha_entrega_simulacion IS NOT NULL) AS entregadas,
  COUNT(*) FILTER (WHERE o.potencia_cierre_fv_kwp IS NOT NULL) AS con_kwp,
  COUNT(*) FILTER (WHERE o.capacidad_cierre_bess_kwh IS NOT NULL) AS con_kwh,
  ROUND(COALESCE(SUM(o.potencia_cierre_fv_kwp),0),2) AS sum_kwp,
  ROUND(COALESCE(SUM(o.capacidad_cierre_bess_kwh),0),2) AS sum_kwh
FROM tb_oportunidades o JOIN tb_cat_tecnologias t ON o.id_tecnologia=t.id
GROUP BY t.id, t.nombre ORDER BY t.id;
```

### B) Distribución KPI a nivel sitio

| grupo | sitios | int_a_tiempo | int_tarde | comp_a_tiempo | comp_tarde |
|-------|--------|--------------|-----------|---------------|------------|
| 1_fv_family | 378 | 230 | 108 | 184 | 154 |
| 2_bess | 18 | 10 | 4 | 10 | 4 |
| 3_hibrido | 45 | 20 | 19 | 18 | 21 |

```sql
SELECT
  CASE WHEN o.id_tecnologia=3 THEN '3_hibrido'
       WHEN o.id_tecnologia=2 THEN '2_bess'
       ELSE '1_fv_family' END AS grupo,
  COUNT(s.id_sitio) AS sitios,
  COUNT(*) FILTER (WHERE s.kpi_status_interno='Entrega a tiempo') AS int_a_tiempo,
  COUNT(*) FILTER (WHERE s.kpi_status_interno='Entrega tarde') AS int_tarde,
  COUNT(*) FILTER (WHERE s.kpi_status_compromiso='Entrega a tiempo') AS comp_a_tiempo,
  COUNT(*) FILTER (WHERE s.kpi_status_compromiso='Entrega tarde') AS comp_tarde
FROM tb_sitios_oportunidad s JOIN tb_oportunidades o ON s.id_oportunidad=o.id_oportunidad
GROUP BY 1 ORDER BY 1;
```

**INVARIANTE clave:** la fila `1_fv_family` (230/108/184/154) NO debe cambiar tras el refactor.
Si cambia, el decouple alteró datos de FV puro = error.

### C) Conteo de registros a corregir (universo del Excel)

> **Actualizado tras migración 109 (saneamiento de ceros):** el universo bajó de 68 a 45.
> Los conteos originales (pre-saneamiento) se conservan entre paréntesis.

| grupo | nº | qué se corrige |
|-------|----|----------------|
| HIBRIDO (tech 3) | 39 | llenar FECHA_FV_TERMINADO + verificar kWp/kWh |
| BESS_CON_KWP (tech 2 con potencia FV > 0) | 2 (era 5) | revisar: BESS no debe traer kWp |
| FV_CON_KWH (tech 1,4,5 con capacidad BESS > 0) | 4 (era 24) | ¿FV puro mal capturado o híbrido mal clasificado? |
| **Total** | **45 (era 68)** | |

Los 23 registros eliminados del universo eran ceros sin sentido (FV con kWh=0, BESS con kWp=0),
saneados por la migración 109. Datos extra: 22 de los 39 híbridos están entregados con kWp FV
nulo o 0 (falta capturar la potencia real); 3 simulaciones adicionales pertenecen a híbridos.

---

## 2. Confirmación de unidades

- **FV → kWp** (kilowatt-pico, potencia). Columna `tb_oportunidades.potencia_cierre_fv_kwp`.
- **BESS → kWh** (kilowatt-hora, energía). Columna `tb_oportunidades.capacidad_cierre_bess_kwh`.

Son magnitudes distintas. Un BESS con valor en el campo kWp, o un FV con valor en kWh,
es error de captura a corregir en el Excel.

---

## 3. Decisiones de negocio (acordadas)

1. **Captura "FV Terminado":** botón/acción **independiente del estatus** en el modal de
   actualizar estatus de Simulación. Graba la fecha real en que terminó FV aunque BESS siga
   pendiente y el estatus global siga activo. (El estatus es lineal y no admite "FV listo,
   BESS pendiente" en una sola columna; por eso es un timestamp, no un estatus.)
2. **BESS puro (tech 2):** se **excluye de las métricas de FV**, pero **se sigue mostrando en
   UI y PDF** cuántos BESS se entregaron a tiempo / tarde, en su propia sección.
3. **Modelo de datos:** **tabla de componentes (full decouple)** — ver sección 4.
4. **Alcance de backfill:** 2026 + híbridos 2025 (todos los híbridos viven en el universo de
   68 registros del Excel).

---

## 4. Modelo nuevo: `tb_entregas_componente`

Una fila por **(entrega física × tecnología presente)**. Unifica `tb_sitios_oportunidad` y
`tb_simulaciones_adicionales` como fuente única de KPIs de entrega.

| Columna | Tipo | Nota |
|---|---|---|
| `id` | bigserial PK | |
| `id_oportunidad` | uuid FK | |
| `id_sitio` | uuid NULL | si origen = sitio |
| `id_sim_adicional` | bigint NULL | si origen = sim_adicional |
| `origen` | text | `'sitio'` \| `'sim_adicional'` |
| `componente` | text CHECK | `'FV'` \| `'BESS'` |
| `area_responsable` | text | `'SIMULACION'` (FV) \| `'ALMACENAMIENTO'` (BESS) |
| `magnitud` | numeric | kWp si FV, kWh si BESS |
| `unidad` | text | `'kWp'` \| `'kWh'` |
| `fecha_entrega` | timestamptz | **clave del decouple**: FV puede ≠ BESS |
| `deadline_calculado` | timestamptz | heredado del padre |
| `deadline_negociado` | timestamptz | heredado del padre |
| `kpi_status_interno` | varchar | `fecha_entrega <= deadline_calculado` |
| `kpi_status_compromiso` | varchar | `fecha_entrega <= COALESCE(negociado, calculado)` |
| `created_at` / `updated_at` | timestamptz | |

- Sitio FV puro → 1 fila FV. Sitio híbrido → 2 filas (FV + BESS).
- **FV puro: FV.fecha_entrega = fecha de cierre actual → KPIs idénticos a hoy (cero regresión).**
- Reglas de KPI iguales a las actuales (`service.py:calcular_kpis_sitio`), pero cada componente
  contra su propia `fecha_entrega`.

---

## 5. Fases de implementación

> Cada fase es un paso separado que requiere aprobación explícita antes de ejecutar.

**Fase 1 — Schema + backfill automático** (`migrations/108_entregas_componente.sql`, idempotente) — **APLICADA 2026-06-15**
- Crear tabla + índices (`id_oportunidad`, `componente`, `area_responsable`, `fecha_entrega`).
- Poblar desde datos actuales (alcance: 2026 + híbridos 2025):
  - FV-family (1,4,5) → 1 fila FV (área SIMULACION).
  - BESS puro (2) → 1 fila BESS (área ALMACENAMIENTO).
  - Híbrido (3) → fila FV + fila BESS; FV.fecha_entrega = fecha conjunta *provisional*.
- **Desviaciones aplicadas vs diseño** (validadas contra PROD): `id_sim_adicional` es `uuid`;
  magnitud viene del PADRE (columnas de sitio en 0), asignada al primer sitio en multisitio;
  regla de componentes = FV si tech!=2, BESS si tech in (2,3).
- **Resultado verificado:** 361 filas (FV 306 / BESS 55). 6 híbridos quedaron fuera por ser
  tipo **Levantamiento** (exclusión correcta), no por error.

**Fase 2 — Excel de corrección + script de import** — **script LISTO** (`scripts/decouple_fv_bess/importar_correccion.py`)
- Excel ya generado (sección 6). El equipo lo llena.
- El script valida (runbook Paso 2), exige `DECOUPLE_DB_DSN` de PROD, verifica que sea PROD,
  es dry-run por defecto (`--apply` para escribir, transaccional). Solo escribe en
  `tb_entregas_componente`: setea FV.fecha_entrega real + recalcula KPI FV, corrige magnitudes.
- **RECLASIFICAR_TECNOLOGIA NO se auto-aplica** (toca `tb_oportunidades`): se reporta como
  seguimiento manual.

**Fase 3 — Captura en vivo: botón "FV Terminado"** — **CÓDIGO LISTO 2026-06-15** (falta desplegar)
- Visible solo `id_tecnologia = 3` (híbrido). Acción independiente del estatus (no lo avanza).
- **Fecha automática** = `now_mx()`, igual que los demás estatus terminales (no se captura a mano).
- **Doble confirmación** antes de aplicar: "¿Estás seguro de marcar FV como terminado?".
- Graba `fecha_entrega` en los componentes FV de la oportunidad, **marca `editado_manual = true`**
  (para que el sync de Fase 5 no lo sobrescriba) y recalcula KPI FV contra los deadlines.
- Endpoint dedicado + permiso `require_module_access('simulacion', editor)`; es idempotente.
- **Implementado:**
  - `db_service.get_fv_terminado()` + `marcar_fv_terminado()` (UPDATE solo `componente='FV'`).
  - `service.marcar_fv_terminado()`: valida tech=3, fecha `now_mx`, sincroniza componentes antes
    de marcar (una op activa puede no tener filas aún).
  - `router.py`: `POST /simulacion/fv-terminado/{id}` + `fv_terminado_fecha` en contexto del modal.
  - `update_oportunidades.html`: banner ámbar (solo `isBess && !isBessOnly`) con `hx-confirm` y
    `hx-target="#form-feedback"`; reusa `success_inline.html` (recarga modal a 700ms).
  - Los 4 módulos compilan; lógica SQL verificada read-only contra PROD (no se ejecutó UPDATE real).

**Fase 6 — Recordatorio diario por correo (16:00 MX)** — decisiones cerradas
- **Scheduling:** **worker task** en `worker.py` con check de hora MX (no GitHub Actions). Patrón:
  loop que despierta y, cuando es 16:00 America/Mexico_City, dispara el envío (con guard de
  idempotencia para no reenviar si el loop corre varias veces en la misma hora).
- **Granularidad:** **un solo correo resumen** a los destinatarios configurados (con desglose por
  responsable en el cuerpo), no uno por responsable.
- **Destinatarios configurables — reusar el patrón del popup comercial** (sección Buzones de admin):
  - Nueva sección colapsable en `templates/admin/partials/content_buzones.html` con **multiselect de
    usuarios activos** (igual que "Configuración Comercial").
  - Guardar en `tb_configuracion_global` con clave nueva, p.ej. `SIMULACION_RECORDATORIO_TARGETS`
    (emails separados por coma), espejo de `COMERCIAL_POPUP_TARGETS`.
  - Endpoint admin `/admin/config/recordatorio-simulaciones` (mismo molde que `/config/comercial`
    en `modules/admin/router.py:659`), con `require_module_access('admin','admin')`.
- **Contenido:** nº de simulaciones **activas** (estatus no terminal, excl. Levantamiento), desglose
  por responsable, y recordatorio de actualizar el estatus de cada oportunidad. Envío vía
  `core/workflow/notification_service.py` (Graph API) + outbox `tb_correos_notificaciones`.
- **Independiente del decouple** — se puede construir en cualquier momento.

**Fase 4 — Reportes + UI + PDF** — **CÓDIGO LISTO 2026-06-16** (falta aplicar `migrations/112` + desplegar)
- Secciones KPI de Simulación: `WHERE componente='FV' AND area_responsable='SIMULACION'`.
- BESS en sección propia (UI + PDF): cuántos a tiempo / tarde.
- Refactor de los CTEs en `modules/simulacion/report_db_service.py` (hoy hacen UNION de
  sitios + sim_adicionales y cuentan `id_sitio`; pasan a contar componentes).
- **DECISIÓN (2026-06-15) — `report_db_service.py` se toca UNA sola vez, aquí:** Montaje hace todo
  su trabajo SIN tocar este archivo (solo `metrics_db_service.py`). Esta Fase 4 es el único refactor
  de `report_db_service.py` e integra de entrada los tres ejes: (1) leer de `tb_entregas_componente`,
  (2) separar sección BESS, (3) filtro `excluir_kpis_simulacion` + `cuenta_para_kpi` (de Montaje).
  Por eso **Montaje va antes que esta Fase 4**, y la exclusión en KPIs de reporte se implementa aquí,
  no en Montaje. Ver sección "Integración" de `MD/PLAN_MONTAJE_OFERTA_KPIS_SIMULACION.md`.

### Guía técnica para reducir la fragilidad de `report_db_service.py` (aprovechar este refactor)

El archivo es frágil por: (a) índices de parámetros calculados a mano (`idx_entregado = len(params) - 8`),
(b) IDs de catálogo pasados como parámetros, (c) el mismo CTE `UNION ALL` repetido en ~6 métodos.
Como la Fase 4 reescribe esas queries de todos modos, aplicar estas mejoras sin costo extra:

- **Nivel 1 — Resolver catálogos DENTRO del SQL (mayor impacto).** En vez de pasar IDs como params
  y calcular `idx_X`, filtrar contra el catálogo:
  ```sql
  -- en vez de:  id_estatus_global IN ($idx_entregado, $idx_perdido, $idx_ganada)
  -- usar:       id_estatus_global IN (SELECT id FROM tb_cat_estatus_oportunidades WHERE cuenta_para_kpi)
  ```
  Elimina la mayoría de los `idx_` calculados. El patrón ya existe en `get_report_tiempo_promedio_global`
  (`WHERE LOWER(nombre) IN (...)`); generalizarlo. **La migración de Montaje a `cuenta_para_kpi` ES
  este fix** — al cambiar `IN (entregado,perdido,ganada)` por `e.cuenta_para_kpi=true`, esos params y
  sus índices desaparecen. Montaje + Fase 4 reducen la fragilidad como efecto secundario.

- **Nivel 2 — Builder de parámetros (mata el `len(params)-N`).** Helper que auto-asigna placeholders:
  ```python
  class P:
      def __init__(self): self.vals = []
      def add(self, v): self.vals.append(v); return f"${len(self.vals)}"
  # uso:  q = f"... WHERE o.fecha_solicitud >= {p.add(fecha_inicio)} ..."; await conn.fetch(q, *p.vals)
  ```
  Elimina el cálculo manual de índices (la clase de bug más peligrosa). ~15 líneas.

- **Nivel 3 — Vista que encapsule el CTE repetido (opcional).** Crear `v_entregas_componente_kpi`
  (el `UNION ALL` + JOINs comunes, ya con `excluir_kpis_simulacion`); los ~6 métodos hacen
  `SELECT … FROM v_entregas_componente_kpi WHERE …` en vez de repetir el CTE. Evaluar según cuánta
  duplicación quede tras migrar a componentes.

Prioridad: Niveles 1 y 2 (alto valor, bajo costo dentro de este refactor); Nivel 3 según convenga.

**Fase 5 — Sincronía** — **CÓDIGO LISTO 2026-06-15** (falta aplicar `migrations/110` + desplegar)
- `migrations/110_entregas_componente_fecha_manual.sql`: añade flag `editado_manual` (protege
  fecha/magnitud puestas a mano por botón/import de un re-sync).
- `db_service.sync_componentes_oportunidad(conn, id_op)`: upsert idempotente por oportunidad
  (misma lógica que mig 108, sin filtro de fecha, KPI computado de fecha-vs-deadline; respeta
  `editado_manual`). Excluye Levantamiento.
- Wired en `service.py`: post-commit y best-effort en `update_simulacion_padre` y
  `update_sitios_batch` (un fallo de sync no revierte el cierre).
- **Orden de despliegue:** aplicar `migrations/110` ANTES de desplegar el código (el sync
  referencia `editado_manual`; sin la columna, el sync falla best-effort y no sincroniza).
- Pendiente opcional: full-sync único para rellenar 2 KPIs NULL históricos (se corrigen solos
  cuando esas oportunidades se toquen).

---

## 6. Excel de corrección — estructura y cómo se generó

**Archivo:** `scripts/decouple_fv_bess/correccion_fv_bess.xlsx`
**Generador:** `scripts/decouple_fv_bess/generar_excel_correccion.py`
**Datos fuente:** `scripts/decouple_fv_bess/_data_prod.json` (snapshot PROD vía MCP, 45 registros
tras saneamiento 109).

### Hojas
- **Instrucciones** — cómo llenar.
- **Correccion** — 45 filas; grises = read-only, amarillas = a llenar.
- **Snapshot** — agregados baseline (sección 1) embebidos para auditar integridad.

### Columnas (confirmadas kWp y kWh)
| Columna | Tipo | Editable |
|---|---|---|
| op_id_estandar, cliente_nombre, tecnologia_actual, grupo_correccion | contexto | no |
| cantidad_sitios, estatus_actual, fecha_solicitud | contexto | no |
| fecha_entrega_conjunta, deadline_calculado, deadline_negociado | contexto | no |
| **kWp_actual** | FV actual | no |
| **kWh_actual** | BESS actual | no |
| **FECHA_FV_TERMINADO** | fecha real FV | **sí** |
| **kWp_CORREGIDO** | FV corregido (kilowatt-pico) | **sí** |
| **kWh_CORREGIDO** | BESS corregido (kilowatt-hora) | **sí** |
| RECLASIFICAR_TECNOLOGIA, NOTAS | opcional | **sí** |
| id_oportunidad | clave del UPDATE | no |

### Regenerar
```bash
# Desde el snapshot PROD ya capturado (default, NO toca BD):
python scripts/decouple_fv_bess/generar_excel_correccion.py

# Desde la BD viva. OJO: .env = DEV. Para PROD exportar el DSN primero:
#   export DECOUPLE_DB_DSN="postgresql://USER:PASS@HOST:6543/postgres"
python scripts/decouple_fv_bess/generar_excel_correccion.py --from-db
```

---

## 7. Runbook para cualquier agente — validar ANTES de ejecutar

### Paso 0 — Confirmar BD objetivo
```sql
SELECT inet_server_addr()::text, current_database(), count(*) AS ops FROM tb_oportunidades;
```
Debe ser PRODUCCIÓN: `ops` ~293 (no 286). Si da 286, estás en DEV → DETENTE.

### Paso 1 — Confirmar que el baseline sigue vigente
Re-ejecutar consultas A, B y C (sección 1). Si los números difieren del snapshot,
**regenerar el Excel** (`--from-db` contra PROD) antes de continuar, porque hay datos nuevos.

### Paso 2 — Validar el Excel lleno (antes del import)
- Filas totales = 45 (o el nuevo conteo de C si el baseline cambió).
- Ninguna `FECHA_FV_TERMINADO` vacía en filas `grupo_correccion = HIBRIDO`.
- `FECHA_FV_TERMINADO` ∈ [fecha_solicitud, hoy], no futura.
- `kWp_CORREGIDO` y `kWh_CORREGIDO` numéricos (sin texto, sin unidades pegadas).
- `op_id_estandar` e `id_oportunidad` sin modificar (claves del UPDATE).
- Para `BESS_CON_KWP`: `kWp_CORREGIDO` debe quedar 0/vacío salvo reclasificación a híbrido.
- Para `FV_CON_KWH`: si `kWh_CORREGIDO` > 0, marcar `RECLASIFICAR_TECNOLOGIA = FV + BESS`.

### Paso 3 — Ejecutar (cada sub-paso pide aprobación explícita)
1. Aplicar `migrations/108_entregas_componente.sql` (crea tabla + backfill automático).
2. Correr el script de import del Excel (Fase 2).

### Paso 4 — Verificación post-ejecución (comparar contra baseline)
```sql
-- 4.1 INVARIANTE: FV-family a nivel sitio NO cambió (debe dar 378/230/108/184/154)
--     (consulta B de la sección 1)

-- 4.2 Cada oportunidad genera las filas componente esperadas
SELECT componente, area_responsable, count(*) FROM tb_entregas_componente GROUP BY 1,2 ORDER BY 1,2;

-- 4.3 Reconciliación de magnitudes: suma kWp FV de componentes vs origen corregido
SELECT componente, unidad, ROUND(SUM(magnitud),2) FROM tb_entregas_componente GROUP BY 1,2;

-- 4.4 Ningún híbrido entregado sin FV.fecha_entrega
SELECT count(*) FROM tb_entregas_componente
WHERE componente='FV' AND fecha_entrega IS NULL
  AND id_oportunidad IN (SELECT id_oportunidad FROM tb_oportunidades WHERE id_tecnologia=3
                         AND fecha_entrega_simulacion IS NOT NULL);  -- esperado 0
```

### Paso 5 — Rollback
- La migración 108 solo AÑADE tabla; revertir = `DROP TABLE tb_entregas_componente`.
- El import de Excel solo escribe en `tb_entregas_componente` (no toca `tb_oportunidades`
  ni `tb_sitios_oportunidad` en Fases 1-2). Las correcciones de unidades que SÍ toquen
  `tb_oportunidades` deben hacerse en un paso aparte, explícito y con su propio backup.

---

## 8. Pendientes / decisiones abiertas

- **24 FV con kWh:** revisar 1×1 en el Excel — ¿son FV puro con dato basura, o híbridos mal
  clasificados? La reclasificación cambia a qué área se reporta cada uno.
- **Granularidad multi-sitio:** los 3 híbridos multi-sitio de 2026 — ¿FECHA_FV_TERMINADO por
  oportunidad o por sitio? Default propuesto: por oportunidad (FV es un entregable de
  ingeniería único), cascada a sitios como hoy.
- **Refresh DEV←PROD:** diferido por pruebas activas. Tras el refresh, validar que DEV ya
  refleje 293 ops antes de probar el flujo ahí.

---

## 9. Fix del modal de actualización — prevención de captura sucia (causa raíz)

**Archivo:** `templates/simulacion/modals/update_oportunidades.html`, bloque "Datos de Cierre".

### Problema
Hoy los campos **Potencia FV (KWp)** y **BESS (KWh)** se renderizan **siempre**, para
todas las tecnologías; solo cambia el asterisco de requerido (`is_bess_related = tech in [2,3]`,
`is_bess_only = tech == 2`, definidos en `router.py:722-723` y expuestos al `x-data` como
`isBess` / `isBessOnly`). Consecuencia:

- Un **FV puro** muestra igual el campo "BESS (KWh)" → se teclea kWh donde no corresponde.
- Un **BESS puro** muestra "Potencia FV (KWp) (opcional)" → se teclea kWp donde no corresponde.

Esta UI es la **causa raíz probable** de los registros sucios que este plan corrige:
**5 BESS con kWp** y **24 FV con kWh** (sección 1.C). Corregir el modal evita reincidir
después del backfill.

### Solución elegida — Implementación (b)

Ocultar el campo no aplicable por tecnología y, para el híbrido, dejar **ambos campos en una
fila** con la etiqueta actual reforzada + helper text de unidades. No requiere cambios de
backend (los flags ya existen en el `x-data`).

**Visibilidad por tecnología:**

| Tecnología | Potencia FV (KWp) | BESS (KWh) |
|---|---|---|
| FV / FV AISLADO / BOMBEO (1,4,5) | visible, requerido `*` | **oculto** |
| BESS puro (2) | **oculto** | visible, requerido `*` |
| **FV + BESS (3)** | visible, requerido `*` | visible, requerido `*` |

**Cambios concretos en el template:**

1. `<div>` del campo FV (envuelve `name="potencia_cierre_fv_kwp"`, ~línea 398):
   añadir `x-show="!isBessOnly"`.
2. `<div>` del campo BESS (envuelve `name="capacidad_cierre_bess_kwh"`, ~línea 414):
   añadir `x-show="isBess"`.
3. Para el híbrido (ambos visibles), reforzar el etiquetado con un helper text bajo el grid,
   visible solo cuando `isBess && !isBessOnly`:
   ```html
   <p class="md:col-span-2 text-[10px] text-gray-500" x-show="isBess && !isBessOnly">
       kWp = potencia FV · kWh = energía BESS. Captura cada valor en su campo correspondiente.
   </p>
   ```
4. Mantener las etiquetas explícitas existentes: **"Potencia FV (KWp)"** y **"BESS (KWh)"**
   (ya indican qué campo es FV y cuál BESS). Mantener la lógica de asterisco/requerido tal cual.

**Notas:**
- `!isBessOnly` cubre "tiene FV" para el catálogo actual (1,3,4,5 tienen FV; solo el 2 no).
  Si a futuro entra una tecnología sin FV, introducir un flag `isFvRelated` explícito.
- Los campos ocultos no deben enviar valor: al estar fuera del flujo de captura evitan que se
  re-introduzca un kWp en BESS puro o un kWh en FV puro.
- Este fix se puede aplicar **antes** del refactor de componentes (es independiente y de bajo
  riesgo), y de hecho conviene desplegarlo cuanto antes para frenar el ingreso de datos sucios.
