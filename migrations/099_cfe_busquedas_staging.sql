-- Staging de busquedas historicas CFE antes de conservar descargas definitivas.

CREATE TABLE IF NOT EXISTS tb_cfe_busquedas (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    servicio_id        UUID        NOT NULL REFERENCES tb_cfe_servicios(id) ON DELETE CASCADE,
    solicitado_por     UUID        REFERENCES tb_usuarios(id_usuario) ON DELETE SET NULL,
    max_periodos       INTEGER     NOT NULL DEFAULT 12 CHECK (max_periodos BETWEEN 1 AND 60),
    estatus            TEXT        NOT NULL DEFAULT 'pendiente',
    mensaje_error      TEXT,
    total_detectados   INTEGER     NOT NULL DEFAULT 0,
    total_descargados  INTEGER     NOT NULL DEFAULT 0,
    creado_en          TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_en          TIMESTAMPTZ NOT NULL DEFAULT now() + interval '6 hours',
    CONSTRAINT tb_cfe_busquedas_estatus_check
        CHECK (estatus IN ('pendiente', 'descargando', 'completado', 'error', 'confirmado', 'descartado', 'expirado'))
);

CREATE TABLE IF NOT EXISTS tb_cfe_busqueda_items (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    busqueda_id         UUID        NOT NULL REFERENCES tb_cfe_busquedas(id) ON DELETE CASCADE,
    periodo             TEXT        NOT NULL,
    etiqueta_periodo    TEXT,
    xml_estatus         TEXT        NOT NULL DEFAULT 'pendiente',
    pdf_estatus         TEXT        NOT NULL DEFAULT 'pendiente',
    xml_nombre_archivo  TEXT,
    pdf_nombre_archivo  TEXT,
    xml_staging_url     TEXT,
    pdf_staging_url     TEXT,
    xml_drive_item_id   TEXT,
    pdf_drive_item_id   TEXT,
    ya_descargado_xml   BOOLEAN     NOT NULL DEFAULT false,
    ya_descargado_pdf   BOOLEAN     NOT NULL DEFAULT false,
    error_mensaje       TEXT,
    decision            TEXT        NOT NULL DEFAULT 'pendiente',
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tb_cfe_busqueda_items_periodo_check
        CHECK (periodo ~ '^20[0-9]{2}-(0[1-9]|1[0-2])$'),
    CONSTRAINT tb_cfe_busqueda_items_xml_estatus_check
        CHECK (xml_estatus IN ('pendiente', 'descargando', 'descargado', 'ya_descargado', 'no_disponible', 'error')),
    CONSTRAINT tb_cfe_busqueda_items_pdf_estatus_check
        CHECK (pdf_estatus IN ('pendiente', 'descargando', 'descargado', 'ya_descargado', 'no_disponible', 'error')),
    CONSTRAINT tb_cfe_busqueda_items_decision_check
        CHECK (decision IN ('pendiente', 'conservado', 'descartado', 'no_aplica')),
    CONSTRAINT tb_cfe_busqueda_items_uq UNIQUE (busqueda_id, periodo)
);

CREATE INDEX IF NOT EXISTS idx_cfe_busquedas_servicio_id
    ON tb_cfe_busquedas(servicio_id);

CREATE INDEX IF NOT EXISTS idx_cfe_busquedas_cola
    ON tb_cfe_busquedas(creado_en)
    WHERE estatus = 'pendiente';

CREATE INDEX IF NOT EXISTS idx_cfe_busquedas_activas
    ON tb_cfe_busquedas(servicio_id)
    WHERE estatus IN ('pendiente', 'descargando');

CREATE INDEX IF NOT EXISTS idx_cfe_busquedas_expira
    ON tb_cfe_busquedas(expira_en)
    WHERE estatus IN ('completado', 'error');

CREATE INDEX IF NOT EXISTS idx_cfe_busqueda_items_busqueda_id
    ON tb_cfe_busqueda_items(busqueda_id);

