-- 032_calculadora_cotizaciones_estatus.sql
-- Agrega columna de estatus a tb_calculadora_cotizaciones para seguimiento del ciclo de vida
-- Estatus: CREADA | ENVIADA | EN_NEGOCIACION | ACEPTADA | RECHAZADA | VENCIDA

ALTER TABLE tb_calculadora_cotizaciones
    ADD COLUMN IF NOT EXISTS estatus VARCHAR(30) NOT NULL DEFAULT 'CREADA',
    ADD COLUMN IF NOT EXISTS estatus_updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS estatus_updated_by UUID REFERENCES tb_usuarios(id_usuario);

CREATE INDEX IF NOT EXISTS idx_calculadora_cotizaciones_estatus
    ON tb_calculadora_cotizaciones (estatus);
