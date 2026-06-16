-- 112_backfill_entregas_componente_historico.sql
-- Decouple FV/BESS - Fase 4: completa tb_entregas_componente para TODO el historico
-- de sitios/sim_adicionales no-levantamiento, no solo 2026 + hibridos 2025 (mig 108).
-- Motivo: los reportes de KPI pasan a leer de tb_entregas_componente; sin este backfill
-- cualquier reporte que abarque 2025 perderia los sitios FV/BESS puros que la mig 108
-- dejo fuera por el filtro de anio (en PROD: 74 de 82 sitios 2025).
--
-- Para FV/BESS puro el decouple es un no-op: 1 componente = el sitio, misma fecha_entrega
-- y mismo kpi_status -> cero regresion (invariante FV-family intacta).
-- Idempotente via NOT EXISTS: solo inserta filas faltantes, nunca actualiza, asi que no
-- pisa correcciones manuales (editado_manual) ni el universo de hibridos ya presente.
-- Misma logica que mig 108 SIN el filtro de anio.
-- NOTA: aplicar en PRODUCCION (MCP Supabase). El .env apunta a DEV.

-- 1. Componentes FV desde SITIOS (tech != 2)
INSERT INTO tb_entregas_componente (
    id_oportunidad, id_sitio, origen, componente, area_responsable,
    magnitud, unidad, fecha_entrega, deadline_calculado, deadline_negociado,
    kpi_status_interno, kpi_status_compromiso
)
SELECT
    s.id_oportunidad, s.id_sitio, 'sitio', 'FV', 'SIMULACION',
    CASE WHEN row_number() OVER (PARTITION BY s.id_oportunidad ORDER BY s.fecha_carga, s.id_sitio) = 1
         THEN o.potencia_cierre_fv_kwp ELSE 0 END,
    'kWp',
    COALESCE(s.fecha_cierre, o.fecha_entrega_simulacion),
    o.deadline_calculado, o.deadline_negociado,
    s.kpi_status_interno, s.kpi_status_compromiso
FROM tb_sitios_oportunidad s
JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
WHERE o.id_tecnologia != 2
  AND o.id_tipo_solicitud IS DISTINCT FROM (SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento')
  AND NOT EXISTS (
        SELECT 1 FROM tb_entregas_componente ec
        WHERE ec.id_sitio = s.id_sitio AND ec.componente = 'FV'
      );

-- 2. Componentes BESS desde SITIOS (tech in (2,3))
INSERT INTO tb_entregas_componente (
    id_oportunidad, id_sitio, origen, componente, area_responsable,
    magnitud, unidad, fecha_entrega, deadline_calculado, deadline_negociado,
    kpi_status_interno, kpi_status_compromiso
)
SELECT
    s.id_oportunidad, s.id_sitio, 'sitio', 'BESS', 'ALMACENAMIENTO',
    CASE WHEN row_number() OVER (PARTITION BY s.id_oportunidad ORDER BY s.fecha_carga, s.id_sitio) = 1
         THEN o.capacidad_cierre_bess_kwh ELSE 0 END,
    'kWh',
    COALESCE(s.fecha_cierre, o.fecha_entrega_simulacion),
    o.deadline_calculado, o.deadline_negociado,
    s.kpi_status_interno, s.kpi_status_compromiso
FROM tb_sitios_oportunidad s
JOIN tb_oportunidades o ON s.id_oportunidad = o.id_oportunidad
WHERE o.id_tecnologia IN (2, 3)
  AND o.id_tipo_solicitud IS DISTINCT FROM (SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento')
  AND NOT EXISTS (
        SELECT 1 FROM tb_entregas_componente ec
        WHERE ec.id_sitio = s.id_sitio AND ec.componente = 'BESS'
      );

-- 3. Componentes FV desde SIMULACIONES ADICIONALES (tech != 2)
INSERT INTO tb_entregas_componente (
    id_oportunidad, id_sim_adicional, origen, componente, area_responsable,
    magnitud, unidad, fecha_entrega, deadline_calculado, deadline_negociado,
    kpi_status_interno, kpi_status_compromiso
)
SELECT
    sa.id_oportunidad, sa.id, 'sim_adicional', 'FV', 'SIMULACION',
    sa.potencia_cierre_fv_kwp, 'kWp',
    sa.fecha_entrega, o.deadline_calculado, o.deadline_negociado,
    sa.kpi_status_interno, sa.kpi_status_compromiso
FROM tb_simulaciones_adicionales sa
JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
WHERE o.id_tecnologia != 2
  AND o.id_tipo_solicitud IS DISTINCT FROM (SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento')
  AND NOT EXISTS (
        SELECT 1 FROM tb_entregas_componente ec
        WHERE ec.id_sim_adicional = sa.id AND ec.componente = 'FV'
      );

-- 4. Componentes BESS desde SIMULACIONES ADICIONALES (tech in (2,3))
INSERT INTO tb_entregas_componente (
    id_oportunidad, id_sim_adicional, origen, componente, area_responsable,
    magnitud, unidad, fecha_entrega, deadline_calculado, deadline_negociado,
    kpi_status_interno, kpi_status_compromiso
)
SELECT
    sa.id_oportunidad, sa.id, 'sim_adicional', 'BESS', 'ALMACENAMIENTO',
    sa.capacidad_cierre_bess_kwh, 'kWh',
    sa.fecha_entrega, o.deadline_calculado, o.deadline_negociado,
    sa.kpi_status_interno, sa.kpi_status_compromiso
FROM tb_simulaciones_adicionales sa
JOIN tb_oportunidades o ON sa.id_oportunidad = o.id_oportunidad
WHERE o.id_tecnologia IN (2, 3)
  AND o.id_tipo_solicitud IS DISTINCT FROM (SELECT id FROM tb_cat_tipos_solicitud WHERE LOWER(nombre) = 'levantamiento')
  AND NOT EXISTS (
        SELECT 1 FROM tb_entregas_componente ec
        WHERE ec.id_sim_adicional = sa.id AND ec.componente = 'BESS'
      );
