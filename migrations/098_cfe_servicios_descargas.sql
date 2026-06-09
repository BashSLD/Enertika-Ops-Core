-- migrations/098_cfe_servicios_descargas.sql
-- Tablas para módulo Recibos CFE: servicios registrados y control de descargas

CREATE TABLE IF NOT EXISTS tb_cfe_servicios (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    numero_servicio TEXT        NOT NULL UNIQUE,
    nombre          TEXT        NOT NULL,
    alias           TEXT,
    lada            TEXT        NOT NULL DEFAULT '55',
    telefono        TEXT        NOT NULL,
    email           TEXT        NOT NULL,
    activo          BOOLEAN     NOT NULL DEFAULT true,
    creado_por      UUID        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tb_cfe_descargas (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    servicio_id     UUID        NOT NULL REFERENCES tb_cfe_servicios(id) ON DELETE CASCADE,
    periodo         TEXT        NOT NULL,
    tipo            TEXT        NOT NULL,
    estatus         TEXT        NOT NULL DEFAULT 'pendiente',
    nombre_archivo  TEXT,
    ruta_sharepoint TEXT,
    error_mensaje   TEXT,
    descargado_por  UUID        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    descargado_en   TIMESTAMPTZ,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tb_cfe_descargas_tipo_check CHECK (tipo IN ('xml', 'pdf')),
    CONSTRAINT tb_cfe_descargas_estatus_check
        CHECK (estatus IN ('pendiente', 'descargando', 'completado', 'error')),
    CONSTRAINT tb_cfe_descargas_uq UNIQUE (servicio_id, periodo, tipo)
);

CREATE INDEX IF NOT EXISTS idx_cfe_descargas_servicio_id ON tb_cfe_descargas(servicio_id);
CREATE INDEX IF NOT EXISTS idx_cfe_descargas_estatus ON tb_cfe_descargas(estatus) WHERE estatus IN ('pendiente','descargando');
CREATE INDEX IF NOT EXISTS idx_cfe_descargas_cola ON tb_cfe_descargas(creado_en) WHERE estatus = 'pendiente';
