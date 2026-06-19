-- Detalle estructurado del intento de alta en MiEspacio (periodos y totales probados).
ALTER TABLE tb_cfe_servicios
  ADD COLUMN IF NOT EXISTS miespacio_detalle_json JSONB;
