-- Indice compuesto para conteo agrupado por proyecto (WHERE estatus='PENDIENTE' AND proyecto_id = ANY($1) GROUP BY proyecto_id), analogo a idx_bom_cot_aprob_proyecto_estatus en tb_bom_cotizacion_aprobaciones

CREATE INDEX IF NOT EXISTS idx_bom_autorizaciones_proyecto_estatus
    ON tb_bom_autorizaciones (proyecto_id, estatus);
