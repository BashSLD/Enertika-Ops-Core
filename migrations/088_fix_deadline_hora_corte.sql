-- Migración 088: Recalcular deadline_calculado y deadline_negociado a la hora de corte correcta.
--
-- Problema:
--   deadline_calculado  → estaba fijo a 17:30 MX (HORA_CORTE_L_V anterior).
--   deadline_negociado  → se guardaba como datetime naive, almacenado como 18:00 UTC = 12:00 MX (bug de timezone).
--
-- Solución:
--   Ambos deadlines se recalculan a 18:00 MX (HORA_CORTE_L_V actual) preservando la fecha original en hora México.
--   Luego se recalculan KPIs en las tres tablas que los almacenan:
--     tb_oportunidades, tb_sitios_oportunidad, tb_simulaciones_adicionales.
--
-- Idempotente: ejecutar más de una vez produce el mismo resultado.

-- 1. Recalcular deadline_calculado (17:30 MX → 18:00 MX)
UPDATE tb_oportunidades
SET deadline_calculado = (
    (deadline_calculado AT TIME ZONE 'America/Mexico_City')::date + TIME '18:00:00'
) AT TIME ZONE 'America/Mexico_City'
WHERE deadline_calculado IS NOT NULL;

-- 2. Recalcular deadline_negociado (bug: 12:00 MX → correcto: 18:00 MX, misma fecha)
UPDATE tb_oportunidades
SET deadline_negociado = (
    (deadline_negociado AT TIME ZONE 'America/Mexico_City')::date + TIME '18:00:00'
) AT TIME ZONE 'America/Mexico_City'
WHERE deadline_negociado IS NOT NULL;

-- 3. Recalcular KPIs en tb_oportunidades
UPDATE tb_oportunidades
SET
    kpi_status_sla_interno = CASE
        WHEN fecha_entrega_simulacion <= deadline_calculado THEN 'Entrega a tiempo'
        ELSE 'Entrega tarde'
    END,
    kpi_status_compromiso = CASE
        WHEN fecha_entrega_simulacion <= COALESCE(deadline_negociado, deadline_calculado)
            THEN 'Entrega a tiempo'
        ELSE 'Entrega tarde'
    END
WHERE fecha_entrega_simulacion IS NOT NULL;

-- 4. Recalcular KPIs en tb_sitios_oportunidad (tiene fecha_cierre propia)
UPDATE tb_sitios_oportunidad s
SET
    kpi_status_interno = CASE
        WHEN s.fecha_cierre <= o.deadline_calculado THEN 'Entrega a tiempo'
        ELSE 'Entrega tarde'
    END,
    kpi_status_compromiso = CASE
        WHEN s.fecha_cierre <= COALESCE(o.deadline_negociado, o.deadline_calculado)
            THEN 'Entrega a tiempo'
        ELSE 'Entrega tarde'
    END
FROM tb_oportunidades o
WHERE s.id_oportunidad = o.id_oportunidad
  AND s.fecha_cierre IS NOT NULL;

-- 5. Recalcular KPIs en tb_sitios_oportunidad (sin fecha_cierre: toma KPI del padre)
UPDATE tb_sitios_oportunidad s
SET
    kpi_status_interno   = o.kpi_status_sla_interno,
    kpi_status_compromiso = o.kpi_status_compromiso
FROM tb_oportunidades o
WHERE s.id_oportunidad = o.id_oportunidad
  AND s.fecha_cierre IS NULL
  AND s.kpi_status_interno IS NOT NULL;

-- 6. Recalcular KPIs en tb_simulaciones_adicionales (usa deadlines del padre)
UPDATE tb_simulaciones_adicionales sa
SET
    kpi_status_interno = CASE
        WHEN sa.fecha_entrega <= o.deadline_calculado THEN 'Entrega a tiempo'
        ELSE 'Entrega tarde'
    END,
    kpi_status_compromiso = CASE
        WHEN sa.fecha_entrega <= COALESCE(o.deadline_negociado, o.deadline_calculado)
            THEN 'Entrega a tiempo'
        ELSE 'Entrega tarde'
    END
FROM tb_oportunidades o
WHERE sa.id_oportunidad = o.id_oportunidad
  AND sa.fecha_entrega IS NOT NULL;
