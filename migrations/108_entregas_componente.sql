-- 108_entregas_componente.sql
-- Decouple FV/BESS: tabla de componentes de entrega (1 fila por entrega x tecnologia
-- presente) + backfill idempotente. FV -> area SIMULACION (kWp); BESS -> area
-- ALMACENAMIENTO (kWh). Permite medir el KPI de FV independiente de BESS en hibridos.
-- Ver PLAN_DECOUPLE_FV_BESS.md secciones 4 y 5.
-- NOTA: aplicar en PRODUCCION (MCP Supabase). El .env apunta a DEV.

-- ============================================================================
-- 1. TABLA
-- ============================================================================
CREATE TABLE IF NOT EXISTS tb_entregas_componente (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_oportunidad        uuid NOT NULL REFERENCES tb_oportunidades(id_oportunidad) ON DELETE CASCADE,
    id_sitio              uuid REFERENCES tb_sitios_oportunidad(id_sitio) ON DELETE CASCADE,
    id_sim_adicional      uuid REFERENCES tb_simulaciones_adicionales(id) ON DELETE CASCADE,
    origen                text NOT NULL CHECK (origen IN ('sitio', 'sim_adicional')),
    componente            text NOT NULL CHECK (componente IN ('FV', 'BESS')),
    area_responsable      text NOT NULL CHECK (area_responsable IN ('SIMULACION', 'ALMACENAMIENTO')),
    magnitud              numeric,
    unidad                text CHECK (unidad IN ('kWp', 'kWh')),
    fecha_entrega         timestamptz,
    deadline_calculado    timestamptz,
    deadline_negociado    timestamptz,
    kpi_status_interno    varchar,
    kpi_status_compromiso varchar,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- 2. INDICES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_entregas_comp_oportunidad ON tb_entregas_componente(id_oportunidad);
CREATE INDEX IF NOT EXISTS idx_entregas_comp_componente  ON tb_entregas_componente(componente);
CREATE INDEX IF NOT EXISTS idx_entregas_comp_area        ON tb_entregas_componente(area_responsable);
CREATE INDEX IF NOT EXISTS idx_entregas_comp_fecha       ON tb_entregas_componente(fecha_entrega);

-- Unicidad para idempotencia: una fila por (sitio, componente) y por (sim_adicional, componente)
CREATE UNIQUE INDEX IF NOT EXISTS uq_entregas_comp_sitio
    ON tb_entregas_componente(id_sitio, componente) WHERE id_sitio IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_entregas_comp_sim
    ON tb_entregas_componente(id_sim_adicional, componente) WHERE id_sim_adicional IS NOT NULL;

-- ============================================================================
-- 3. BACKFILL (idempotente via NOT EXISTS)
-- Alcance: oportunidades del 2026 + hibridos (tech 3) del 2025; excluye Levantamientos.
-- Regla de componentes (igual que el modal): FV si tech != 2; BESS si tech in (2,3).
-- Magnitud: para origen=sitio viene del PADRE (las columnas de sitio estan en 0);
--   en multisitio se asigna solo al primer sitio (fecha_carga) por (oportunidad,componente)
--   para que SUM(magnitud) reconcilie con el padre. Para sim_adicional, magnitud propia.
-- ============================================================================

-- 3.1 Componentes FV desde SITIOS (tech != 2)
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
  AND (
        EXTRACT(YEAR FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') = 2026
        OR (o.id_tecnologia = 3 AND EXTRACT(YEAR FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') = 2025)
      )
  AND NOT EXISTS (
        SELECT 1 FROM tb_entregas_componente ec
        WHERE ec.id_sitio = s.id_sitio AND ec.componente = 'FV'
      );

-- 3.2 Componentes BESS desde SITIOS (tech in (2,3))
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
  AND (
        EXTRACT(YEAR FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') = 2026
        OR (o.id_tecnologia = 3 AND EXTRACT(YEAR FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') = 2025)
      )
  AND NOT EXISTS (
        SELECT 1 FROM tb_entregas_componente ec
        WHERE ec.id_sitio = s.id_sitio AND ec.componente = 'BESS'
      );

-- 3.3 Componentes FV desde SIMULACIONES ADICIONALES (tech != 2)
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
  AND (
        EXTRACT(YEAR FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') = 2026
        OR (o.id_tecnologia = 3 AND EXTRACT(YEAR FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') = 2025)
      )
  AND NOT EXISTS (
        SELECT 1 FROM tb_entregas_componente ec
        WHERE ec.id_sim_adicional = sa.id AND ec.componente = 'FV'
      );

-- 3.4 Componentes BESS desde SIMULACIONES ADICIONALES (tech in (2,3))
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
  AND (
        EXTRACT(YEAR FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') = 2026
        OR (o.id_tecnologia = 3 AND EXTRACT(YEAR FROM o.fecha_solicitud AT TIME ZONE 'America/Mexico_City') = 2025)
      )
  AND NOT EXISTS (
        SELECT 1 FROM tb_entregas_componente ec
        WHERE ec.id_sim_adicional = sa.id AND ec.componente = 'BESS'
      );
