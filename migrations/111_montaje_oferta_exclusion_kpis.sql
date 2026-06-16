-- Migración 111: estatus 'Montaje de oferta' + exclusión de KPIs/métricas en Simulación
-- Idempotente. Ejecutar ANTES de desplegar el código que dependa de este cambio.
--
-- Introduce dos estatus "especiales" (Monitoreo de Cotización y Montaje de oferta) que:
--   - pueden saltarse el flujo normal En Revisión -> Entregado,
--   - pueden pasar después a Entregado,
--   - no cuentan en KPIs ni en métricas operativas (flag por oportunidad),
--   - se contabilizan por separado desde historial de estatus.

-- 1. Flag en catálogo: marca los estatus que activan la exclusión de KPIs al entrar en ellos.
ALTER TABLE tb_cat_estatus_oportunidades
    ADD COLUMN IF NOT EXISTS activa_exclusion_kpis_simulacion boolean NOT NULL DEFAULT false;

-- 2. Flag en oportunidad: se activa al entrar a un estatus especial y se conserva
--    aunque la oportunidad pase después a Entregado.
ALTER TABLE tb_oportunidades
    ADD COLUMN IF NOT EXISTS excluir_kpis_simulacion boolean NOT NULL DEFAULT false;

-- 3. Nuevo estatus 'Montaje de oferta' (idempotente).
INSERT INTO tb_cat_estatus_oportunidades
    (nombre, descripcion, color_hex, activo, modulo_aplicable, cuenta_para_kpi, es_estatus_final)
SELECT
    'Montaje de oferta',
    'Oportunidad en montaje de oferta; caso especial que no cuenta en KPIs ni métricas operativas.',
    '#0EA5E9',
    true,
    'SIMULACION',
    false,
    false
WHERE NOT EXISTS (
    SELECT 1 FROM tb_cat_estatus_oportunidades
    WHERE LOWER(nombre) = 'montaje de oferta'
      AND modulo_aplicable = 'SIMULACION'
);

-- 4. Marcar Montaje de oferta como estatus especial de exclusión.
UPDATE tb_cat_estatus_oportunidades
SET activa_exclusion_kpis_simulacion = true,
    cuenta_para_kpi = false,
    es_estatus_final = false
WHERE LOWER(nombre) = 'montaje de oferta'
  AND modulo_aplicable = 'SIMULACION';

-- 5. Monitoreo de Cotización pasa a ser también estatus especial de exclusión.
UPDATE tb_cat_estatus_oportunidades
SET activa_exclusion_kpis_simulacion = true,
    cuenta_para_kpi = false,
    es_estatus_final = false
WHERE LOWER(nombre) = 'monitoreo de cotización'
  AND modulo_aplicable = 'SIMULACION';

-- 6. Reordenar el catálogo SIMULACION (idempotente — UPDATE SET).
UPDATE tb_cat_estatus_oportunidades
SET orden = CASE nombre
    WHEN 'Pendiente'               THEN 1
    WHEN 'En Proceso'              THEN 2
    WHEN 'En Revisión'             THEN 3
    WHEN 'Comentarios Recibidos'   THEN 4
    WHEN 'Entregado'               THEN 5
    WHEN 'Monitoreo de Cotización' THEN 6
    WHEN 'Montaje de oferta'       THEN 7
    WHEN 'Ganada'                  THEN 8
    WHEN 'Cancelado'               THEN 9
    WHEN 'Perdido'                 THEN 10
    ELSE orden
END
WHERE modulo_aplicable = 'SIMULACION';

-- 7. Backfill: toda oportunidad con historial en un estatus especial queda excluida.
--    Se usa historial (no estatus actual) porque pueden haber terminado en Entregado.
UPDATE tb_oportunidades o
SET excluir_kpis_simulacion = true
WHERE EXISTS (
    SELECT 1
    FROM tb_historial_estatus h
    JOIN tb_cat_estatus_oportunidades e ON e.id = h.id_estatus_nuevo
    WHERE h.id_oportunidad = o.id_oportunidad
      AND e.activa_exclusion_kpis_simulacion = true
)
AND COALESCE(o.excluir_kpis_simulacion, false) = false;
