-- 055: Inbox de CFDIs descargados del SAT pendientes de matching
CREATE TABLE IF NOT EXISTS tb_sat_inbox (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES tb_sat_jobs(id) ON DELETE CASCADE,
    uuid_cfdi       TEXT NOT NULL,
    rfc_emisor      TEXT NOT NULL,
    nombre_emisor   TEXT,
    fecha_cfdi      DATE,
    total           NUMERIC(18,2),
    moneda          TEXT NOT NULL DEFAULT 'MXN',
    sharepoint_url  TEXT NOT NULL DEFAULT '',
    sharepoint_item_id TEXT,
    estado          TEXT NOT NULL DEFAULT 'pendiente',
    factura_id      INT REFERENCES tb_facturas(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_sat_inbox_uuid_cfdi UNIQUE (uuid_cfdi)
);

CREATE INDEX IF NOT EXISTS idx_sat_inbox_estado ON tb_sat_inbox(estado);
CREATE INDEX IF NOT EXISTS idx_sat_inbox_job_id ON tb_sat_inbox(job_id);
CREATE INDEX IF NOT EXISTS idx_sat_inbox_created ON tb_sat_inbox(created_at DESC);
