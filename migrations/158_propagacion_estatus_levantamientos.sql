-- Migracion 158: propagacion de estatus Levantamientos -> Oportunidades (schema + correccion de datos PROD)
-- Ver _Planes_Activos/2026-07-23-propagacion-estatus-levantamientos-PLAN.md

-- 0. Sincroniza la secuencia si quedo desalineada del MAX(id) real (split-brain DEV/PROD:
--    filas sembradas con id explicito sin actualizar la secuencia despues). Idempotente.
SELECT setval('tb_cat_motivos_cierre_id_seq', (SELECT MAX(id) FROM tb_cat_motivos_cierre));

-- 1. Nuevo motivo de cierre "Sin seguimiento / inactividad" (CANCELACION, no forzosamente inviable)
INSERT INTO tb_cat_motivos_cierre (categoria, motivo, aplicacion, es_no_viable, activo)
SELECT 'Otros', 'Sin seguimiento / inactividad', 'CANCELACION', false, true
WHERE NOT EXISTS (
    SELECT 1 FROM tb_cat_motivos_cierre WHERE motivo = 'Sin seguimiento / inactividad'
);

-- 2. Motivo catalogado de cancelacion en Levantamientos, coexiste con motivo_pospone (texto libre)
ALTER TABLE tb_levantamientos
    ADD COLUMN IF NOT EXISTS id_motivo_cancelacion integer NULL
    REFERENCES tb_cat_motivos_cierre(id);

-- 3. Anti-spam del recordatorio periodico (worker, Paso 8 del plan)
ALTER TABLE tb_oportunidades
    ADD COLUMN IF NOT EXISTS recordatorio_lev_cancelado_at timestamptz NULL;

-- 4. Descripcion del estatus 'cancelado' describia solo el estado viejo; ahora documenta la propagacion
UPDATE tb_cat_estatus_levantamiento
SET descripcion = 'El levantamiento fue cancelado. Cuando todos los levantamientos de la oportunidad quedan cancelados con motivo inviable, la oportunidad tambien se cierra.'
WHERE codigo = 'cancelado';

-- 5. Correccion de datos PROD (verificado via MCP 2026-07-27)
-- JOSE DOMINGUEZ RANCHO (OP - 2606091414): OP Pendiente, 3 levantamientos Cancelado -> cerrar OP
UPDATE tb_oportunidades o
SET id_estatus_global = (SELECT id FROM tb_cat_estatus_oportunidades WHERE nombre = 'Cancelado'),
    id_motivo_cierre = (SELECT id FROM tb_cat_motivos_cierre WHERE motivo = 'Decisión Corporativa / Fuerza Mayor')
WHERE o.op_id_estandar = 'OP - 2606091414'
  AND o.id_estatus_global = (SELECT id FROM tb_cat_estatus_oportunidades WHERE nombre = 'Pendiente')
  AND NOT EXISTS (
      SELECT 1 FROM tb_levantamientos l
      JOIN tb_cat_estatus_levantamiento el ON el.id = l.id_estatus_global
      WHERE l.id_oportunidad = o.id_oportunidad AND el.codigo <> 'cancelado'
  );

-- GLOBAL CRUISES (OP - 2603240754): OP Pendiente, 1 levantamiento Cancelado -> cerrar OP, motivo nuevo
UPDATE tb_oportunidades o
SET id_estatus_global = (SELECT id FROM tb_cat_estatus_oportunidades WHERE nombre = 'Cancelado'),
    id_motivo_cierre = (SELECT id FROM tb_cat_motivos_cierre WHERE motivo = 'Sin seguimiento / inactividad')
WHERE o.op_id_estandar = 'OP - 2603240754'
  AND o.id_estatus_global = (SELECT id FROM tb_cat_estatus_oportunidades WHERE nombre = 'Pendiente')
  AND NOT EXISTS (
      SELECT 1 FROM tb_levantamientos l
      JOIN tb_cat_estatus_levantamiento el ON el.id = l.id_estatus_global
      WHERE l.id_oportunidad = o.id_oportunidad AND el.codigo <> 'cancelado'
  );

-- CEMEX (OP - 2605260833) y HONEYWELL (OP - 2607020548): excluidas a proposito, no se tocan.
