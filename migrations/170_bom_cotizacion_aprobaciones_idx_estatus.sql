-- Fase 3 doc 33: dashboard de Direccion filtra por estatus solo (sin bom_id/proyecto_id conocido)

CREATE INDEX IF NOT EXISTS idx_bom_cot_aprob_estatus
    ON tb_bom_cotizacion_aprobaciones(estatus);
