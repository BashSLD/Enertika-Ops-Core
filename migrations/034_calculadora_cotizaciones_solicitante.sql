-- Migración 034: campo solicitante_id en cotizaciones de pólizas
-- Permite vincular una cotización con el usuario de Comercial que la solicitó

ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS solicitante_id UUID REFERENCES tb_usuarios(id_usuario);

CREATE INDEX IF NOT EXISTS idx_calculadora_cotizaciones_solicitante
    ON tb_calculadora_cotizaciones (solicitante_id)
    WHERE solicitante_id IS NOT NULL;
