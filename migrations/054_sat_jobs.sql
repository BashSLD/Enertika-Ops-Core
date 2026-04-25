-- 054: Jobs de descarga masiva SAT
CREATE TABLE IF NOT EXISTS tb_sat_jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    estado              TEXT NOT NULL DEFAULT 'iniciando',
    empresa             TEXT NOT NULL DEFAULT 'ISA',
    fecha_inicio_rango  DATE NOT NULL,
    fecha_fin_rango     DATE NOT NULL,
    id_solicitud_sat    TEXT,
    cfdi_encontrados    INT NOT NULL DEFAULT 0,
    cfdi_duplicados     INT NOT NULL DEFAULT 0,
    mensaje_error       TEXT,
    creado_por          UUID REFERENCES tb_usuarios(id_usuario),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sat_jobs_estado ON tb_sat_jobs(estado);
CREATE INDEX IF NOT EXISTS idx_sat_jobs_created ON tb_sat_jobs(created_at DESC);
