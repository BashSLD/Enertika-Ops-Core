-- Migración 047: tabla de staging para XMLs procesados sin confirmar
-- Permite detectar XMLs que el usuario subió pero cerró el modal sin vincular al comprobante

CREATE TABLE IF NOT EXISTS tb_xml_staging (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uuid_factura    TEXT NOT NULL UNIQUE,
    emisor_rfc      TEXT NOT NULL,
    emisor_nombre   TEXT,
    monto           NUMERIC(15,2) NOT NULL,
    moneda          TEXT NOT NULL DEFAULT 'MXN',
    tipo_factura    TEXT NOT NULL DEFAULT 'NORMAL',
    match_type      TEXT NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'PENDIENTE',
    uploaded_by_id  UUID REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_xml_staging_estado
    ON tb_xml_staging (estado)
    WHERE estado = 'PENDIENTE';

CREATE INDEX IF NOT EXISTS idx_xml_staging_uploaded_by
    ON tb_xml_staging (uploaded_by_id);
