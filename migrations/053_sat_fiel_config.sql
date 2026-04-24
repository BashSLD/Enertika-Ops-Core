-- 053: Configuracion FIEL SAT para descarga de CFDIs del SAT
CREATE TABLE IF NOT EXISTS tb_sat_fiel_config (
    id              SERIAL PRIMARY KEY,
    empresa         TEXT NOT NULL DEFAULT 'ISA',
    sp_path_cer     TEXT NOT NULL DEFAULT '',
    sp_path_key     TEXT NOT NULL DEFAULT '',
    password_fiel   TEXT NOT NULL DEFAULT '',
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Un solo registro activo por empresa
CREATE UNIQUE INDEX IF NOT EXISTS uq_sat_fiel_config_empresa_activo
    ON tb_sat_fiel_config(empresa) WHERE activo = TRUE;
