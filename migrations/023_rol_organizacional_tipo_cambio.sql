-- Migración 023: rol_organizacional en tb_usuarios + tabla tb_tipo_cambio
-- 2026-03-18

-- 1. Rol organizacional (campo único excluyente — jefe_ingenieria, jefe_construccion, director)
ALTER TABLE tb_usuarios
    ADD COLUMN IF NOT EXISTS rol_organizacional VARCHAR(30) DEFAULT NULL;

-- 2. Tabla tipo de cambio Banxico (USD/MXN FIX — serie SF43718)
CREATE TABLE IF NOT EXISTS tb_tipo_cambio (
    id          SERIAL PRIMARY KEY,
    fecha       DATE         NOT NULL UNIQUE,
    tasa_mxn    NUMERIC(10,4) NOT NULL,
    fuente      VARCHAR(20)  NOT NULL DEFAULT 'BANXICO',
    creado_en   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tipo_cambio_fecha ON tb_tipo_cambio (fecha DESC);
