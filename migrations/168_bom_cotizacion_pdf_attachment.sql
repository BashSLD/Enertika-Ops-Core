-- Fase 2 doc 33: PDF real de cotizaciones BOM via SharePoint (columna dedicada + origen_slug)

ALTER TABLE tb_documentos_attachments
    ADD COLUMN IF NOT EXISTS id_bom_cotizacion UUID REFERENCES tb_bom_cotizaciones(id);

CREATE INDEX IF NOT EXISTS idx_documentos_bom_cotizacion
    ON tb_documentos_attachments(id_bom_cotizacion);

INSERT INTO tb_cat_origenes_adjuntos (slug, descripcion, activo)
VALUES ('cotizacion_bom', 'PDF de cotizacion de compras post-BOM', TRUE)
ON CONFLICT (slug) DO NOTHING;
