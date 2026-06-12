-- migrations/104_cfe_miespacio_estatus.sql
-- Estado de registro del servicio en CFE MiEspacio. Separa el alta en MiEspacio
-- (job del worker) de la descarga de recibos. El worker reclama los 'pendiente'.

ALTER TABLE tb_cfe_servicios
    ADD COLUMN IF NOT EXISTS miespacio_estatus TEXT NOT NULL DEFAULT 'no_verificado';

ALTER TABLE tb_cfe_servicios
    ADD COLUMN IF NOT EXISTS miespacio_error TEXT;

ALTER TABLE tb_cfe_servicios
    ADD COLUMN IF NOT EXISTS miespacio_verificado_en TIMESTAMPTZ;

DO $$ BEGIN
    ALTER TABLE tb_cfe_servicios
        ADD CONSTRAINT tb_cfe_servicios_miespacio_estatus_check
        CHECK (miespacio_estatus IN ('no_verificado', 'pendiente', 'registrando', 'registrado', 'error'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Cola del worker: reclamar pendientes en orden de creacion (FIFO).
CREATE INDEX IF NOT EXISTS idx_cfe_servicios_miespacio_pendiente
    ON tb_cfe_servicios(creado_en)
    WHERE miespacio_estatus = 'pendiente';
