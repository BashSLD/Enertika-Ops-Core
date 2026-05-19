-- Extender expediente documental de proveedores con metadata de SharePoint y versionado.

ALTER TABLE tb_proveedor_documentos
    ADD COLUMN IF NOT EXISTS id_documento_attachment UUID,
    ADD COLUMN IF NOT EXISTS nombre_archivo TEXT,
    ADD COLUMN IF NOT EXISTS tipo_contenido TEXT,
    ADD COLUMN IF NOT EXISTS tamano_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS drive_item_id TEXT,
    ADD COLUMN IF NOT EXISTS parent_drive_id TEXT,
    ADD COLUMN IF NOT EXISTS folder_path TEXT,
    ADD COLUMN IF NOT EXISTS periodo VARCHAR(7),
    ADD COLUMN IF NOT EXISTS nombre_documento_personalizado TEXT,
    ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS reemplaza_a UUID,
    ADD COLUMN IF NOT EXISTS estatus VARCHAR(20) DEFAULT 'vigente';

ALTER TABLE tb_proveedor_documentos
    ALTER COLUMN version SET DEFAULT 1,
    ALTER COLUMN estatus SET DEFAULT 'vigente';

UPDATE tb_proveedor_documentos
SET version = 1
WHERE version IS NULL;

UPDATE tb_proveedor_documentos
SET estatus = CASE
        WHEN COALESCE(vigente, true) THEN 'vigente'
        ELSE 'historico'
    END
WHERE estatus IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_prov_docs_attachment'
          AND conrelid = 'tb_proveedor_documentos'::regclass
    ) THEN
        ALTER TABLE tb_proveedor_documentos
        ADD CONSTRAINT fk_prov_docs_attachment
        FOREIGN KEY (id_documento_attachment)
        REFERENCES tb_documentos_attachments(id_documento)
        ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_prov_docs_reemplaza_a'
          AND conrelid = 'tb_proveedor_documentos'::regclass
    ) THEN
        ALTER TABLE tb_proveedor_documentos
        ADD CONSTRAINT fk_prov_docs_reemplaza_a
        FOREIGN KEY (reemplaza_a)
        REFERENCES tb_proveedor_documentos(id)
        ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_prov_docs_estatus'
          AND conrelid = 'tb_proveedor_documentos'::regclass
    ) THEN
        ALTER TABLE tb_proveedor_documentos
        ADD CONSTRAINT ck_prov_docs_estatus
        CHECK (estatus IN ('vigente', 'historico', 'eliminado'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_prov_docs_tipo_periodo
    ON tb_proveedor_documentos(id_proveedor, tipo_documento, periodo);

CREATE INDEX IF NOT EXISTS idx_prov_docs_estatus
    ON tb_proveedor_documentos(id_proveedor, estatus);

CREATE INDEX IF NOT EXISTS idx_prov_docs_drive_item
    ON tb_proveedor_documentos(drive_item_id);

CREATE INDEX IF NOT EXISTS idx_prov_docs_attachment
    ON tb_proveedor_documentos(id_documento_attachment);
