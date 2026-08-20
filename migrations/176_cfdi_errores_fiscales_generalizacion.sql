-- Doc: generaliza tb_compras_xml_errores a tb_cfdi_errores_fiscales (core/cfdi/)
-- La migracion 172 (ya aplicada en DEV y PROD) creo tb_compras_xml_errores con columna
-- `origen` y CHECK fijo a los canales de Compras. Esta migracion la generaliza para que
-- Finanzas y el futuro flujo de Construccion tambien puedan auditar sus propios errores
-- fiscales: renombra tabla/columna/indices y agrega modulo_slug (FK real a tb_cat_modulos)
-- en vez de seguir ampliando el CHECK.
--
-- Usa bloques DO $$ guardados contra information_schema para los RENAME -- a diferencia
-- de ADD COLUMN/CREATE INDEX/DROP CONSTRAINT (que ya son idempotentes con IF [NOT] EXISTS),
-- RENAME TABLE/COLUMN no lo son de forma nativa en Postgres si se re-ejecutan sobre el
-- nombre ya renombrado. Ver decision 9 de _Planes_Activos/2026-08-19-cfdi-servicio-compartido.md.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'tb_compras_xml_errores'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'tb_cfdi_errores_fiscales'
    ) THEN
        ALTER TABLE tb_compras_xml_errores RENAME TO tb_cfdi_errores_fiscales;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tb_cfdi_errores_fiscales' AND column_name = 'origen'
    ) THEN
        ALTER TABLE tb_cfdi_errores_fiscales RENAME COLUMN origen TO canal;
    END IF;
END $$;

-- El CHECK original solo conocia los canales de Compras (CARGA_MANUAL/BUZON_SAT) --
-- cada modulo valida sus propios canales en su capa de aplicacion (decision 3).
ALTER TABLE tb_cfdi_errores_fiscales DROP CONSTRAINT IF EXISTS tb_compras_xml_errores_origen_check;

ALTER TABLE tb_cfdi_errores_fiscales ADD COLUMN IF NOT EXISTS modulo_slug VARCHAR(50);

-- Backfill: toda fila existente antes de esta migracion vino de Compras (unico
-- consumidor hasta hoy). Idempotente por construccion (WHERE modulo_slug IS NULL).
UPDATE tb_cfdi_errores_fiscales SET modulo_slug = 'compras' WHERE modulo_slug IS NULL;

ALTER TABLE tb_cfdi_errores_fiscales ALTER COLUMN modulo_slug SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_cfdi_errores_fiscales_modulo'
    ) THEN
        ALTER TABLE tb_cfdi_errores_fiscales
            ADD CONSTRAINT fk_cfdi_errores_fiscales_modulo
            FOREIGN KEY (modulo_slug) REFERENCES tb_cat_modulos(slug);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_cfdi_errores_fiscales_modulo_slug ON tb_cfdi_errores_fiscales(modulo_slug);

ALTER INDEX IF EXISTS idx_compras_xml_errores_created_at RENAME TO idx_cfdi_errores_fiscales_created_at;
ALTER INDEX IF EXISTS idx_compras_xml_errores_uuid_factura RENAME TO idx_cfdi_errores_fiscales_uuid_factura;

-- FK uploaded_by_id sin indice de cobertura (advisor de performance de Supabase) --
-- get_errores_fiscales_paginado hace LEFT JOIN tb_usuarios ON id_usuario = uploaded_by_id.
CREATE INDEX IF NOT EXISTS idx_cfdi_errores_fiscales_uploaded_by ON tb_cfdi_errores_fiscales(uploaded_by_id);
