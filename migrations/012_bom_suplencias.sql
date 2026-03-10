-- Migration 012: BOM suplencias (user configures their own substitute with end date)
-- Idempotent

CREATE TABLE IF NOT EXISTS tb_bom_suplencias (
    id          SERIAL PRIMARY KEY,
    titular_id  UUID NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    suplente_id UUID NOT NULL REFERENCES tb_usuarios(id_usuario) ON DELETE CASCADE,
    fecha_fin   DATE NOT NULL,
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT no_auto_suplencia CHECK (titular_id != suplente_id)
);

CREATE INDEX IF NOT EXISTS idx_bom_suplencias_titular
    ON tb_bom_suplencias (titular_id, activo, fecha_fin);
CREATE INDEX IF NOT EXISTS idx_bom_suplencias_suplente
    ON tb_bom_suplencias (suplente_id, activo, fecha_fin);
